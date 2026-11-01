import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_home = tempfile.mkdtemp(prefix="lana-test-")
os.environ["LANA_HOME"] = _home

from lana import config, games, instances, machine  # noqa: E402

FAKE = {
    "id": "fake", "name": "Faux jeu",
    "install": {"type": "none"},
    "run": {"runtime": "native", "command": ["sleep", "300"], "cwd": "."},
    "requirements": {"ram_gb_min": 4, "ram_gb_recommended": 16, "disk_gb": 1},
    "savegame": "save",
    "save_import": [{"label": "Fichier test", "extensions": [".sav"], "magic": "MAGI", "target": "world.sav"}],
    "config": {"file": "cfg.json", "format": "json", "initial": {"name": "x", "pw": "{random}"}},
    "fields": [
        {"key": "name", "label": "Nom", "type": "text", "default": "x"},
        {"key": "sub.level", "label": "Niveau", "type": "float", "min": 0.5, "max": 2, "default": 1},
        {"key": "sub.day", "label": "Jour", "type": "minutes_ns", "min": 2, "max": 60, "default": 30},
        {"key": "mode", "label": "Mode", "type": "enum", "options": ["a", "b"], "default": "a"},
        {"key": "tags", "label": "Tags", "type": "tags", "options": ["x", "y"], "default": []},
        {"key": "groups", "label": "Groupes", "type": "collection", "min_items": 1, "unique": ["name"],
         "item": [{"key": "name", "label": "Nom", "type": "text", "default": "g"},
                  {"key": "ok", "label": "Ok", "type": "bool", "default": False}]},
    ],
}
games._cache["fake"] = FAKE


class ConfigTests(unittest.TestCase):
    def test_paths(self):
        d = {}
        config.set_path(d, "a.b.c", 1)
        self.assertEqual(d, {"a": {"b": {"c": 1}}})
        self.assertEqual(config.get_path(d, "a.b.c"), 1)
        self.assertIs(config.get_path(d, "a.x", None), None)

    def test_defaults_when_missing(self):
        ui = config.to_ui(FAKE, {})
        self.assertEqual(ui["sub.level"], 1)
        self.assertEqual(ui["sub.day"], 30)
        self.assertEqual(ui["groups"], [])

    def test_apply_converts_and_preserves_unknown_keys(self):
        data = {"keep": {"me": 1}, "groups": []}
        out = config.apply_ui(FAKE, data, {"sub.day": 10, "sub.level": 1.2, "groups": [{"name": "a", "ok": True}]})
        self.assertEqual(out["sub"]["day"], 10 * config.NS_PER_MIN)
        self.assertEqual(out["keep"], {"me": 1})
        self.assertEqual(config.to_ui(FAKE, out)["sub.day"], 10)
        self.assertEqual(data["groups"], [])  # l'original n'est pas modifié

    def test_validation(self):
        bad = [{"sub.level": 9}, {"sub.level": "abc"}, {"mode": "z"}, {"name": "  "}, {"tags": ["nope"]},
               {"groups": []}, {"groups": [{"name": "a"}, {"name": "a"}]}, {"sub.day": 1}]
        for values in bad:
            with self.assertRaises(ValueError, msg=str(values)):
                config.apply_ui(FAKE, {}, values)

    def test_initial_config_randomizes_tokens(self):
        a, b = config.initial_config(FAKE), config.initial_config(FAKE)
        self.assertNotEqual(a["pw"], "{random}")
        self.assertNotEqual(a["pw"], b["pw"])


class GameDefinitionTests(unittest.TestCase):
    def test_enshrouded_definition_is_consistent(self):
        game = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "games", "enshrouded.json"), encoding="utf-8"))
        keys = [f["key"] for f in game["fields"]]
        self.assertEqual(len(keys), len(set(keys)))
        initial = config.initial_config(game)
        ui = config.to_ui(game, initial)
        # La config initiale doit être acceptée telle quelle par la validation.
        config.apply_ui(game, initial, ui)
        for port in game["ports"]:
            self.assertIn(port["from"], keys)


class MachineTests(unittest.TestCase):
    base = {"ram_gb": 8.0, "disk_free_gb": 100, "tools": {"wine": "/x/wine", "java": None}}

    def test_verdicts(self):
        self.assertEqual(machine.verdict({"ram_gb_min": 4, "ram_gb_recommended": 8, "disk_gb": 5}, ["wine"], self.base)["level"], "ok")
        self.assertEqual(machine.verdict({"ram_gb_min": 4, "ram_gb_recommended": 16, "disk_gb": 5}, [], self.base)["level"], "warn")
        self.assertEqual(machine.verdict({"ram_gb_min": 16, "ram_gb_recommended": 32, "disk_gb": 5}, [], self.base)["level"], "bad")
        self.assertEqual(machine.verdict({"ram_gb_min": 2, "ram_gb_recommended": 4, "disk_gb": 500}, [], self.base)["level"], "bad")

    def test_missing_tool_is_reported(self):
        v = machine.verdict({"ram_gb_min": 1, "ram_gb_recommended": 1, "disk_gb": 1}, ["java"], self.base)
        self.assertEqual(v["missing"], ["java"])
        self.assertEqual(v["level"], "warn")


class InstanceLifecycleTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_home, ignore_errors=True)

    def make(self):
        inst = instances.Instance.create("fake")
        os.makedirs(inst.server_dir)
        meta = inst.meta()
        meta["installed"] = True
        json.dump(meta, open(inst.meta_path, "w"))
        return inst

    def test_start_stop_backup_restore(self):
        inst = self.make()
        save = os.path.join(inst.server_dir, "save")
        os.makedirs(save)
        open(os.path.join(save, "world"), "w").write("v1")

        self.assertFalse(inst.running())
        inst.start()
        self.assertTrue(inst.running())
        with self.assertRaises(instances.InstanceError):
            inst.start()
        with self.assertRaises(instances.InstanceError):
            inst.restore("whatever.tar.gz")

        inst.stop()  # sauvegarde automatique avant l'arrêt
        self.assertFalse(inst.running())
        self.assertEqual(len(inst.backups()), 1)

        open(os.path.join(save, "world"), "w").write("v2")
        inst.restore(inst.backups()[-1]["name"])
        self.assertEqual(open(os.path.join(save, "world")).read(), "v1")

    def test_ids_are_validated(self):
        for bad in ("../x", "A", "a b", ""):
            with self.assertRaises(instances.InstanceError):
                instances.Instance(bad)

    def test_unique_ids(self):
        a, b = instances.Instance.create("fake"), instances.Instance.create("fake")
        self.assertNotEqual(a.id, b.id)


def read(path):
    with open(path) as fh:
        return fh.read()


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as fh:
        fh.write(text)


class ExportImportTests(unittest.TestCase):
    def make(self, content="v1"):
        inst = instances.Instance.create("fake")
        os.makedirs(inst.server_dir)
        meta = inst.meta()
        meta["installed"] = True
        write(inst.meta_path, json.dumps(meta))
        write(os.path.join(inst.server_dir, "save", "world.sav"), content)
        return inst

    def world(self, inst):
        return os.path.join(inst.server_dir, "save", "world.sav")

    def tmp(self, data, name="up.bin"):
        path = os.path.join(_home, name)
        write(path, data, "wb" if isinstance(data, bytes) else "w")
        return path

    def evil_archive(self, member_name, kind="file"):
        path = os.path.join(_home, "evil.tar.gz")
        import io
        import tarfile
        with tarfile.open(path, "w:gz") as tar:
            info = tarfile.TarInfo(member_name)
            if kind == "symlink":
                info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
                tar.addfile(info)
            else:
                data = b"pwned"
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return path

    def test_export_then_import_archive_restores_the_world(self):
        inst = self.make("v1")
        name = inst.backup("export")
        write(self.world(inst), "v2")
        archive = os.path.join(_home, "from-elsewhere.tar.gz")
        shutil.copyfile(inst.backup_path(name), archive)
        inst.import_save(archive, "from-elsewhere.tar.gz")
        self.assertEqual(read(self.world(inst)), "v1")
        self.assertTrue(any("avant-import" in b["name"] for b in inst.backups()))

    def test_single_game_file_import(self):
        inst = self.make("old")
        msg = inst.import_save(self.tmp(b"MAGIdata", "x.sav"), "My World.SAV")
        self.assertIn("importé", msg)
        self.assertEqual(read(self.world(inst)), "MAGIdata")
        self.assertTrue(any("avant-import" in b["name"] for b in inst.backups()))

    def test_wrong_magic_or_extension_leaves_save_untouched(self):
        inst = self.make("keep")
        with self.assertRaises(instances.InstanceError):
            inst.import_save(self.tmp(b"NOPEdata"), "x.sav")
        with self.assertRaises(instances.InstanceError) as ctx:
            inst.import_save(self.tmp(b"MAGIdata"), "x.zip")
        self.assertIn(".sav", str(ctx.exception))  # le message liste les formats acceptés
        self.assertEqual(read(self.world(inst)), "keep")
        self.assertEqual(inst.backups(), [])

    def test_malicious_archives_are_rejected_before_touching_anything(self):
        inst = self.make("keep")
        cases = [("../evil", "file"), ("/abs/evil", "file"), ("other/evil", "file"),
                 ("save/../../evil", "file"), ("save/link", "symlink")]
        for member, kind in cases:
            with self.assertRaises(instances.InstanceError, msg=member):
                inst.import_save(self.evil_archive(member, kind), "evil.tar.gz")
            self.assertEqual(read(self.world(inst)), "keep", member)
        self.assertEqual(inst.backups(), [])
        self.assertFalse(os.path.exists(os.path.join(_home, "evil")))

    def test_corrupt_archive_is_rejected(self):
        inst = self.make("keep")
        with self.assertRaises(instances.InstanceError):
            inst.import_save(self.tmp(b"not a tar at all"), "bad.tar.gz")
        self.assertEqual(read(self.world(inst)), "keep")

    def test_import_refused_while_running(self):
        inst = self.make("keep")
        inst.start()
        try:
            with self.assertRaises(instances.InstanceError):
                inst.import_save(self.tmp(b"MAGIdata"), "x.sav")
            self.assertEqual(read(self.world(inst)), "keep")
        finally:
            inst.stop(backup=False)

    def test_backup_label_cannot_escape_backup_dir(self):
        inst = self.make()
        name = inst.backup("../../evil")
        self.assertNotIn("/", name)
        self.assertTrue(os.path.isfile(os.path.join(inst.backup_dir, name)))
        with self.assertRaises(instances.InstanceError):
            inst.backup_path("../instance.json")
        with self.assertRaises(instances.InstanceError):
            inst.backup_path("/etc/passwd")

    def test_restoring_the_oldest_backup_survives_pruning(self):
        inst = self.make("first")
        oldest = inst.backup("a00")
        for i in range(1, instances.KEEP_BACKUPS):
            inst.backup("a%02d" % i)
        write(self.world(inst), "later")
        inst.restore(oldest)  # l'archivage préalable ne doit pas supprimer `oldest` avant lecture
        self.assertEqual(read(self.world(inst)), "first")
        self.assertLessEqual(len(inst.backups()), instances.KEEP_BACKUPS)


if __name__ == "__main__":
    unittest.main()
