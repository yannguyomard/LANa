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


GAMES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "games")
FIELD_TYPES = ("text", "int", "float", "bool", "enum", "tags", "minutes_ns", "collection")


def real_definitions():
    for fname in sorted(os.listdir(GAMES_DIR)):
        if fname.endswith(".json"):
            with open(os.path.join(GAMES_DIR, fname), encoding="utf-8") as fh:
                yield fname, json.load(fh)


class AllGameDefinitionsTests(unittest.TestCase):
    """Contrôles communs à tous les jeux : une erreur dans un fichier JSON se voit ici, pas chez l'utilisateur."""

    def test_every_definition_is_internally_consistent(self):
        names = [g["id"] for _, g in real_definitions()]
        self.assertGreaterEqual(len(names), 5)
        self.assertEqual(len(names), len(set(names)))
        for fname, game in real_definitions():
            with self.subTest(game=game["id"]):
                self.assertEqual(fname, game["id"] + ".json")
                keys = [f["key"] for f in game["fields"]]
                self.assertEqual(len(keys), len(set(keys)), "clés en double")
                defaults = {}
                for f in game["fields"]:
                    self.assertIn(f["type"], FIELD_TYPES, f["key"])
                    for needed in ("label", "group") + (() if f["type"] == "collection" else ("default",)):
                        self.assertIn(needed, f, f["key"])
                    if f["type"] in ("int", "float", "minutes_ns"):
                        self.assertLessEqual(f["min"], f["default"], f["key"])
                        self.assertLessEqual(f["default"], f["max"], f["key"])
                    if f["type"] == "enum":
                        self.assertIn(f["default"], f["options"], f["key"])
                        for value in f.get("labels", {}):
                            self.assertIn(value, f["options"], f["key"])
                    if f["key"].startswith("lana:"):
                        defaults[f["key"][5:]] = f["default"]
                for port in game["ports"]:
                    self.assertIn(port["from"], keys)
                # L'adresse de connexion et les arguments de lancement doivent se remplir avec les défauts.
                names_ = {f["key"]: f.get("default") for f in game["fields"] if "." not in f["key"] and ":" not in f["key"]}
                names_.update(defaults)
                game["connect"].format(lan_ip="1.2.3.4", **names_)
                for arg in game["run"]["command"]:
                    arg.format(**defaults)
                self.assertIn(game["run"]["runtime"], ("wine", "java", "native"))
                self.assertIn(game["config"]["format"], ("json", "properties", "ue_options"))
                if "compat" in game:
                    self.assertIn(game["compat"]["level"], ("warn", "bad"))
                    self.assertTrue(game["compat"]["note"])

    def test_initial_config_is_accepted_by_validation(self):
        for _, game in real_definitions():
            if game["config"].get("seed_from"):
                continue  # le fichier de départ est celui du jeu, absent des tests
            with self.subTest(game=game["id"]):
                initial = config.initial_config(game)
                ui = config.to_ui(game, initial)
                config.apply_ui(game, initial, {k: v for k, v in ui.items() if not k.startswith("lana:")})

    def test_game_with_known_incompatibility_is_not_installable(self):
        for _, game in real_definitions():
            if game.get("compat", {}).get("level") == "bad":
                v = machine.verdict(game["requirements"], [], {"ram_gb": 64, "disk_free_gb": 1000, "tools": {}}, game["compat"])
                self.assertEqual(v["level"], "bad")
                self.assertIn(game["compat"]["note"], v["messages"])


class MachineTests(unittest.TestCase):
    base = {"ram_gb": 8.0, "disk_free_gb": 100, "tools": {"wine": "/x/wine", "java": None}}

    def test_verdicts(self):
        self.assertEqual(machine.verdict({"ram_gb_min": 4, "ram_gb_recommended": 8, "disk_gb": 5}, ["wine"], self.base)["level"], "ok")
        self.assertEqual(machine.verdict({"ram_gb_min": 4, "ram_gb_recommended": 16, "disk_gb": 5}, [], self.base)["level"], "warn")
        self.assertEqual(machine.verdict({"ram_gb_min": 16, "ram_gb_recommended": 32, "disk_gb": 5}, [], self.base)["level"], "bad")
        self.assertEqual(machine.verdict({"ram_gb_min": 2, "ram_gb_recommended": 4, "disk_gb": 500}, [], self.base)["level"], "bad")

    def test_missing_tool_is_reported(self):
        v = machine.verdict({"ram_gb_min": 1, "ram_gb_recommended": 1, "disk_gb": 1}, ["wine"], dict(self.base, tools={"wine": None, "java": None}))
        self.assertEqual(v["missing"], ["wine"])
        self.assertEqual(v["level"], "warn")

    def test_missing_java_is_not_a_problem_because_lana_downloads_it(self):
        v = machine.verdict({"ram_gb_min": 1, "ram_gb_recommended": 1, "disk_gb": 1}, ["java"], self.base)
        self.assertEqual(v["level"], "ok")
        self.assertEqual(v["missing"], [])
        self.assertTrue(any("Java" in m for m in v["messages"]))

    def test_java_version_parsing(self):
        self.assertEqual(machine.parse_java_major('openjdk version "21.0.13" 2026-10-21'), 21)
        self.assertEqual(machine.parse_java_major('openjdk version "25" 2026-09-16'), 25)
        self.assertEqual(machine.parse_java_major('java version "1.8.0_392"'), 8)
        self.assertIsNone(machine.parse_java_major("Unable to locate a Java Runtime."))


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


PROPS = {
    "id": "fakeprops", "name": "Faux Minecraft",
    "install": {"type": "none"},
    "eula": {"label": "CLUF", "url": "https://example.test/eula", "file": "eula.txt", "content": "eula=true\n"},
    "run": {"runtime": "native", "command": ["sleep", "300"], "cwd": "."},
    "requirements": {"ram_gb_min": 1, "ram_gb_recommended": 1, "disk_gb": 1},
    "savegame": "world",
    "world_zip": {"label": "Monde (.zip)", "marker": "level.dat"},
    "connect": "{lan_ip}:{server-port}",
    "config": {"file": "server.properties", "format": "properties", "initial": {"motd": "hi", "server-port": 25565}},
    "fields": [
        {"key": "motd", "label": "Message", "type": "text", "default": "x"},
        {"key": "server-port", "label": "Port", "type": "int", "min": 1024, "max": 65535, "default": 25565},
        {"key": "pvp", "label": "PvP", "type": "bool", "default": True},
        {"key": "rcon.port", "label": "Port rcon", "type": "int", "min": 1, "max": 65535, "default": 25575},
        {"key": "lana:memory_mb", "label": "Mémoire", "type": "int", "min": 512, "max": 16384, "default": 1536},
    ],
}
games._cache["fakeprops"] = PROPS


class PropertiesTests(unittest.TestCase):
    def make(self, text="#Minecraft server properties\nmotd=Old\npvp=false\nextra-key=keep me\n"):
        inst = instances.Instance.create("fakeprops")
        os.makedirs(inst.server_dir)
        meta = inst.meta()
        meta["installed"] = True
        write(inst.meta_path, json.dumps(meta))
        write(os.path.join(inst.server_dir, "server.properties"), text)
        return inst

    def props(self, inst):
        return read(os.path.join(inst.server_dir, "server.properties"))

    def test_read_is_typed_and_falls_back_to_defaults(self):
        ui = self.make().read_config()
        self.assertEqual(ui["motd"], "Old")
        self.assertIs(ui["pvp"], False)
        self.assertEqual(ui["server-port"], 25565)      # absent du fichier : défaut du jeu
        self.assertEqual(ui["rcon.port"], 25575)        # une clé avec un point reste une clé
        self.assertEqual(ui["lana:memory_mb"], 1536)

    def test_write_keeps_comments_order_and_unknown_keys(self):
        inst = self.make()
        values = inst.read_config()
        values.update({"motd": "New", "pvp": True, "rcon.port": 30000})
        inst.write_config(values)
        text = self.props(inst)
        self.assertTrue(text.startswith("#Minecraft server properties\nmotd=New\npvp=true\nextra-key=keep me\n"))
        self.assertIn("rcon.port=30000", text)
        self.assertEqual(inst.read_config()["rcon.port"], 30000)

    def test_lana_settings_stay_out_of_the_game_file(self):
        inst = self.make()
        values = inst.read_config()
        values["lana:memory_mb"] = 2048
        inst.write_config(values)
        self.assertNotIn("lana", self.props(inst))
        self.assertEqual(inst.meta()["settings"], {"memory_mb": 2048})
        self.assertEqual(inst.read_config()["lana:memory_mb"], 2048)

    def test_newline_in_text_cannot_inject_a_property(self):
        inst = self.make()
        values = inst.read_config()
        values["motd"] = "hello\nenable-rcon=true"
        with self.assertRaises(ValueError):
            inst.write_config(values)
        self.assertNotIn("enable-rcon", self.props(inst))

    def test_minecraft_definition_is_consistent(self):
        game = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "games", "minecraft.json"), encoding="utf-8"))
        keys = [f["key"] for f in game["fields"]]
        self.assertEqual(len(keys), len(set(keys)))
        ui = config.to_ui(game, config.initial_config(game))
        config.apply_ui(game, config.initial_config(game), ui)
        for port in game["ports"]:
            self.assertIn(port["from"], keys)
        self.assertEqual(game["connect"].format(lan_ip="1.2.3.4", **{"server-port": 25565}), "1.2.3.4:25565")
        self.assertTrue(game["eula"]["url"].startswith("https://"))


UE = {
    "id": "fakeue", "name": "Faux Palworld",
    "install": {"type": "none"},
    "run": {"runtime": "native", "command": ["sleep", "300"], "cwd": "."},
    "requirements": {"ram_gb_min": 1, "ram_gb_recommended": 1, "disk_gb": 1},
    "savegame": "Pal/Saved/SaveGames",
    "config": {"file": "Pal/Saved/Config/WindowsServer/PalWorldSettings.ini", "format": "ue_options",
               "section": "/Script/Pal.PalGameWorldSettings", "seed_from": "Default.ini",
               "initial": {"ServerName": "Mon serveur", "AdminPassword": "{random}"}},
    "fields": [
        {"key": "ServerName", "label": "Nom", "type": "text", "default": "x", "maxlen": 60},
        {"key": "AdminPassword", "label": "Admin", "type": "text", "default": ""},
        {"key": "ExpRate", "label": "XP", "type": "float", "min": 0.1, "max": 20, "default": 1},
        {"key": "ServerPlayerMaxNum", "label": "Joueurs", "type": "int", "min": 1, "max": 32, "default": 32},
        {"key": "bIsPvP", "label": "PvP", "type": "bool", "default": False},
        {"key": "DeathPenalty", "label": "Mort", "type": "enum", "options": ["None", "Item", "All"], "default": "All"},
    ],
}
games._cache["fakeue"] = UE
UE_DEFAULT = ('; défauts du jeu\n[/Script/Pal.PalGameWorldSettings]\n'
              'OptionSettings=(Difficulty=None,ExpRate=1.000000,ServerName="Default Palworld Server",'
              'ServerDescription="a, b (c)",bIsPvP=False,DenyTechnologyList=("PALBOX","Repair,Bench"),'
              'DeathPenalty=All,ServerPlayerMaxNum=32,AdminPassword="")\n')


class UnrealOptionsTests(unittest.TestCase):
    def make(self):
        inst = instances.Instance.create("fakeue")
        os.makedirs(inst.server_dir)
        write(os.path.join(inst.server_dir, "Default.ini"), UE_DEFAULT)
        return inst

    def ini(self, inst):
        return read(os.path.join(inst.server_dir, UE["config"]["file"]))

    def test_initial_config_starts_from_the_games_own_defaults(self):
        inst = self.make()
        config.write_initial(UE, inst.server_dir)
        ui = config.to_ui(UE, config.read_file(UE, inst.server_dir))
        self.assertEqual(ui["ServerName"], "Mon serveur")             # imposé par LANa
        self.assertEqual(ui["ExpRate"], 1.0)                          # repris du fichier du jeu
        self.assertEqual(ui["ServerPlayerMaxNum"], 32)
        self.assertNotEqual(ui["AdminPassword"], "{random}")
        self.assertTrue(len(ui["AdminPassword"]) >= 8)
        text = self.ini(inst)
        self.assertIn("DenyTechnologyList=(\"PALBOX\",\"Repair,Bench\")", text)  # clé inconnue : conservée telle quelle
        self.assertIn("ServerDescription=\"a, b (c)\"", text)                   # virgules et parenthèses entre guillemets

    def test_write_uses_the_games_formatting_and_keeps_the_rest(self):
        inst = self.make()
        config.write_initial(UE, inst.server_dir)
        values = config.to_ui(UE, config.read_file(UE, inst.server_dir))
        values.update({"ExpRate": 1.2, "bIsPvP": True, "DeathPenalty": "Item", "ServerName": 'Les "Pals", rois'})
        config.write_file(UE, inst.server_dir, config.apply_ui(UE, config.read_file(UE, inst.server_dir), values))
        text = self.ini(inst)
        self.assertIn("ExpRate=1.200000", text)
        self.assertIn("bIsPvP=True", text)
        self.assertIn("DeathPenalty=Item", text)
        self.assertTrue(text.startswith("; défauts du jeu\n[/Script/Pal.PalGameWorldSettings]\n"))
        self.assertIn("Difficulty=None", text)
        back = config.to_ui(UE, config.read_file(UE, inst.server_dir))
        self.assertEqual(back["ServerName"], 'Les "Pals", rois')    # aller-retour avec guillemets et virgule
        self.assertIs(back["bIsPvP"], True)

    def test_split_ignores_commas_inside_quotes_and_parentheses(self):
        parts = config._split_top_level('A=1,B="x,y",C=("p","q,r"),D="a\\"b,c"')
        self.assertEqual(parts, ['A=1', 'B="x,y"', 'C=("p","q,r")', 'D="a\\"b,c"'])

    def test_ini_without_option_line_gets_one(self):
        inst = instances.Instance.create("fakeue")
        os.makedirs(inst.server_dir)
        config.write_file(UE, inst.server_dir, {"ServerName": "Neuf"})
        self.assertIn("[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(ServerName=\"Neuf\")", self.ini(inst))


class EulaTests(unittest.TestCase):
    def test_install_refuses_without_explicit_acceptance(self):
        inst = instances.Instance.create("fakeprops")
        for accepted in (False, None):
            with self.assertRaises(instances.InstanceError) as ctx:
                inst.install(accept_eula=bool(accepted))
            self.assertIn("contrat de licence", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(inst.server_dir, "eula.txt")))


class ZipWorldImportTests(unittest.TestCase):
    def make(self):
        inst = instances.Instance.create("fakeprops")
        os.makedirs(inst.server_dir)
        meta = inst.meta()
        meta["installed"] = True
        write(inst.meta_path, json.dumps(meta))
        write(os.path.join(inst.server_dir, "world", "level.dat"), "old")
        return inst

    def zipfile(self, entries, symlink=None):
        import zipfile
        path = os.path.join(_home, "w.zip")
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
            if symlink:
                info = zipfile.ZipInfo(symlink)
                info.external_attr = 0o120777 << 16
                zf.writestr(info, "/etc/passwd")
        return path

    def test_world_at_zip_root(self):
        inst = self.make()
        inst.import_save(self.zipfile({"level.dat": "new", "region/r.0.0.mca": "R"}), "mon monde.zip")
        self.assertEqual(read(os.path.join(inst.server_dir, "world", "level.dat")), "new")
        self.assertEqual(read(os.path.join(inst.server_dir, "world", "region", "r.0.0.mca")), "R")
        self.assertTrue(any("avant-import" in b["name"] for b in inst.backups()))

    def test_world_inside_one_folder_with_macos_junk(self):
        inst = self.make()
        inst.import_save(self.zipfile({"MonMonde/level.dat": "new", "MonMonde/data/x": "1",
                                       "__MACOSX/MonMonde/._level.dat": "junk", "MonMonde/.DS_Store": "junk"}), "w.zip")
        self.assertEqual(read(os.path.join(inst.server_dir, "world", "level.dat")), "new")
        self.assertFalse(os.path.exists(os.path.join(inst.server_dir, "world", "MonMonde")))
        self.assertFalse(os.path.exists(os.path.join(inst.server_dir, "world", ".DS_Store")))

    def test_bad_zips_leave_the_world_untouched(self):
        inst = self.make()
        cases = {
            "pas un monde": self.zipfile({"readme.txt": "x"}),
            "traversée": self.zipfile({"level.dat": "x", "../evil": "x"}),
            "chemin absolu": self.zipfile({"level.dat": "x", "/evil": "x"}),
            "hors du monde": self.zipfile({"A/level.dat": "x", "B/other": "x"}),
            "lien": self.zipfile({"level.dat": "x"}, symlink="link"),
        }
        for label, path in cases.items():
            with self.assertRaises(instances.InstanceError, msg=label):
                inst.import_save(path, "w.zip")
            self.assertEqual(read(os.path.join(inst.server_dir, "world", "level.dat")), "old", label)
        with self.assertRaises(instances.InstanceError):
            inst.import_save(self.tmp_garbage(), "w.zip")
        self.assertEqual(inst.backups(), [])
        self.assertFalse(os.path.exists(os.path.join(_home, "evil")))

    def tmp_garbage(self):
        path = os.path.join(_home, "garbage.zip")
        write(path, b"not a zip", "wb")
        return path

    def test_zip_is_refused_for_games_without_world_zip(self):
        inst = instances.Instance.create("fake")
        os.makedirs(os.path.join(inst.server_dir, "save"))
        meta = inst.meta()
        meta["installed"] = True
        write(inst.meta_path, json.dumps(meta))
        with self.assertRaises(instances.InstanceError):
            inst.import_save(self.zipfile({"level.dat": "x"}), "w.zip")


if __name__ == "__main__":
    unittest.main()
