import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_home = tempfile.mkdtemp(prefix="lana-test-")
os.environ["LANA_HOME"] = _home

from lana import config, games, instances, jobs, machine, mods, players, runtime, system, upnp, versions, web  # noqa: E402

FAKE = {
    "id": "fake", "name": "Faux jeu",
    "install": {"type": "none"},
    "run": {"runtime": "native", "command": [sys.executable, "-c", "import time; time.sleep(300)"], "cwd": "."},
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
                names_.update({f["key"].replace(".", "_"): f.get("default") for f in game["fields"] if "." in f["key"] and ":" not in f["key"] and "[" not in f["key"]})
                game["connect"].format(lan_ip="1.2.3.4", **names_)
                for run in [game["run"]] + [game["run"][p] for p in ("linux", "windows") if p in game["run"]]:
                    for arg in run["command"]:
                        arg.format(**defaults)
                    self.assertIn(run.get("runtime", game["run"]["runtime"]), ("wine", "java", "native"))
                self.assertIn(game["config"]["format"], ("json", "properties", "ue_options", "ini", "cfg", "xml_props", "xml_elements", "arma", "none"))
                spec = game["install"]
                self.assertIn(spec["type"], ("steamcmd", "mojang", "download", "upload"))
                self.assertTrue(spec["check_file"])
                if spec["type"] == "steamcmd":
                    self.assertIsInstance(spec["appid"], int)
                if spec["type"] == "upload":
                    self.assertTrue(spec.get("help"))
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
                v = machine.verdict(game["requirements"], [], {"ram_gb": 64, "disk_free_gb": 1000, "tools": {}}, dict(game["compat"], platforms=None))
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
    "run": {"runtime": "native", "command": [sys.executable, "-c", "import time; time.sleep(300)"], "cwd": "."},
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
    "run": {"runtime": "native", "command": [sys.executable, "-c", "import time; time.sleep(300)"], "cwd": "."},
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

    def test_world_into_slot_subfolder(self):
        """Sons of the Forest : le dossier de partie va dans Saves/DedicatedServer/Multiplayer/<emplacement>."""
        game = dict(PROPS, id="fakeslot", world_zip={"label": "Partie (.zip)", "marker": "SaveData.zip",
                                                     "into": "DedicatedServer/Multiplayer/{slot:010d}"})
        game["config"] = dict(PROPS["config"], initial=dict(PROPS["config"]["initial"], slot=3))
        game["fields"] = PROPS["fields"] + [{"key": "slot", "label": "Emplacement", "type": "int", "min": 1, "max": 9, "default": 3}]
        games._cache["fakeslot"] = game
        inst = instances.Instance.create("fakeslot")
        os.makedirs(inst.server_dir)
        write(inst.meta_path, json.dumps(dict(inst.meta(), installed=True)))
        config.write_initial(game, inst.server_dir)
        other = os.path.join(inst.server_dir, "world", "DedicatedServer", "Multiplayer", "0000000001", "SaveData.zip")
        write(other, "autre emplacement")
        inst.import_save(self.zipfile({"0000000001/SaveData.zip": "partie", "0000000001/x.name": ""}), "0000000001.zip")
        slot = os.path.join(inst.server_dir, "world", "DedicatedServer", "Multiplayer", "0000000003")
        self.assertEqual(read(os.path.join(slot, "SaveData.zip")), "partie")
        self.assertEqual(read(other), "autre emplacement")   # les autres emplacements ne sont pas touchés
        self.assertTrue(any("avant-import" in b["name"] for b in inst.backups()))

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




PLAYERS_GAME = {
    "id": "fakeplayers", "name": "Faux jeu multijoueur",
    "install": {"type": "none"},
    "run": {"runtime": "native", "command": [sys.executable, "-c", "import time; time.sleep(300)"], "cwd": "."},
    "requirements": {"ram_gb_min": 1, "ram_gb_recommended": 1, "disk_gb": 1},
    "savegame": "world", "log_file": "game.log",
    "players": {"stats": "minecraft",
                "join": r"^\[(?P<time>\d\d:\d\d:\d\d)\] (?P<name>\w+) joined$",
                "leave": r"^\[(?P<time>\d\d:\d\d:\d\d)\] (?P<name>\w+) left$"},
    "config": {"file": "cfg.json", "format": "json", "initial": {}},
    "fields": [],
}
games._cache["fakeplayers"] = PLAYERS_GAME


class PlayerTrackingTests(unittest.TestCase):
    def make(self, running):
        inst = instances.Instance.create("fakeplayers")
        self.addCleanup(shutil.rmtree, inst.dir, True)
        os.makedirs(inst.server_dir)
        inst._save_meta(dict(inst.meta(), installed=True))
        inst.running = lambda: running
        return inst

    def write_log(self, inst, lines, mode="w"):
        with open(os.path.join(inst.server_dir, "game.log"), mode, encoding="utf-8") as fh:
            fh.write("".join(l + "\n" for l in lines))

    @staticmethod
    def clock(offset):
        return time.strftime("%H:%M:%S", time.localtime(time.time() - offset))

    @staticmethod
    def real_games():
        folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "games")
        for fname in sorted(os.listdir(folder)):
            with open(os.path.join(folder, fname), encoding="utf-8") as fh:
                yield json.load(fh)

    def test_exemples_de_chaque_jeu_sont_reconnus(self):
        checked = 0
        for game in self.real_games():
            spec = game.get("players")
            if not spec:
                continue
            checked += 1
            with self.subTest(game=game["id"]):
                join = players.parse_line(game, spec["sample"]["join"], time.time())
                leave = players.parse_line(game, spec["sample"]["leave"], time.time())
                self.assertEqual(join[0], "join")
                self.assertEqual(leave[0], "leave")
                self.assertIsNone(players.parse_line(game, "[12:00:00] [Server thread/INFO]: <Steve> joined the game", time.time()))
        self.assertGreaterEqual(checked, 3)

    def test_noms_extraits_des_vraies_lignes(self):
        by_id = {g["id"]: g for g in self.real_games()}
        enshrouded, palworld = by_id["enshrouded"], by_id["palworld"]
        minecraft = by_id["minecraft"]
        for line, kind in (("[02:27:54] [Server thread/INFO]: System chat: Humainlanash joined the game", "join"),   # vrai journal (1.21)
                           ("[12:34:56] [Server thread/INFO]: Steve joined the game", "join"),                      # anciennes versions
                           ("[12:40:01] [Server thread/INFO]: Steve left the game", "leave")):
            found = players.parse_line(minecraft, line, time.time())
            self.assertEqual(found[0], kind, line)
        self.assertEqual(players.parse_line(minecraft, "[02:27:54] [Server thread/INFO]: System chat: Humainlanash joined the game", time.time())[1], "Humainlanash")
        self.assertIsNone(players.parse_line(minecraft, "[12:00:00] [Server thread/INFO]: <Steve> Bob joined the game", time.time()))
        self.assertEqual(players.parse_line(enshrouded, enshrouded["players"]["sample"]["join"], time.time())[1], "Verba Lanash")
        self.assertEqual(players.parse_line(enshrouded, enshrouded["players"]["sample"]["leave"], time.time())[1], "Zajabel")
        found = players.parse_line(palworld, palworld["players"]["sample"]["join"], time.time())
        self.assertEqual((found[1], found[2]), ("Zajabel", "steam_76561198000000000"))

    def test_sessions_et_statistiques(self):
        inst = self.make(running=True)
        self.write_log(inst, ["[%s] Alice joined" % self.clock(600), "[%s] Bob joined" % self.clock(500),
                              "[%s] Bob left" % self.clock(200), "[%s] Bob joined" % self.clock(100), "bruit"])
        out = players.report(inst)
        by_name = {p["name"]: p for p in out["players"]}
        self.assertTrue(by_name["Alice"]["online"])
        self.assertTrue(by_name["Bob"]["online"])
        self.assertEqual(by_name["Bob"]["sessions"], 2)
        self.assertAlmostEqual(by_name["Bob"]["longest"], 300, delta=5)
        self.assertEqual(out["totals"]["unique"], 2)
        self.assertEqual(out["totals"]["peak"], 2)
        self.assertEqual(out["totals"]["online"], 2)
        self.assertEqual(out["players"][0]["online"], True)

    def test_lecture_incrementale_sans_doublon(self):
        inst = self.make(running=True)
        self.write_log(inst, ["[%s] Alice joined" % self.clock(300)])
        players.update(inst)
        players.update(inst)   # relecture : rien ne change
        self.write_log(inst, ["[%s] Alice left" % self.clock(100)], mode="a")
        out = players.report(inst)
        alice = out["players"][0]
        self.assertEqual(alice["sessions"], 1)
        self.assertFalse(alice["online"])
        self.assertAlmostEqual(alice["seconds"], 200, delta=5)

    def test_ligne_incomplete_attend_la_suite(self):
        inst = self.make(running=True)
        with open(os.path.join(inst.server_dir, "game.log"), "w") as fh:
            fh.write("[%s] Alice jo" % self.clock(10))
        self.assertEqual(players.report(inst)["totals"]["unique"], 0)
        with open(os.path.join(inst.server_dir, "game.log"), "a") as fh:
            fh.write("ined\n")
        self.assertEqual(players.report(inst)["totals"]["unique"], 1)

    def test_arret_du_serveur_ferme_les_sessions(self):
        inst = self.make(running=False)
        self.write_log(inst, ["[%s] Alice joined" % self.clock(300)])
        out = players.report(inst)
        self.assertFalse(out["players"][0]["online"])
        self.assertEqual(out["events"][0]["kind"], "stop")

    def test_journal_remplace_est_relu_depuis_le_debut(self):
        inst = self.make(running=True)
        self.write_log(inst, ["[%s] Alice joined" % self.clock(300), "[%s] Alice left" % self.clock(250)])
        players.update(inst)
        self.write_log(inst, ["[%s] Bob joined" % self.clock(60)])   # nouveau journal, plus court
        names = {p["name"] for p in players.report(inst)["players"]}
        self.assertEqual(names, {"Alice", "Bob"})

    def test_heure_du_jour_dans_le_futur_date_d_hier(self):
        now = time.time()
        future = time.strftime("%H:%M:%S", time.localtime(now + 3600))
        self.assertAlmostEqual(players.resolve_time({"time": future}, now), now + 3600 - 86400, delta=2)
        self.assertEqual(players.resolve_time({}, now), now)
        self.assertEqual(players.resolve_time({"time": "n'importe quoi"}, now), now)

    def test_statistiques_minecraft(self):
        inst = self.make(running=False)
        stats = os.path.join(inst.server_dir, "world", "stats")
        advs = os.path.join(inst.server_dir, "world", "advancements")
        os.makedirs(stats)
        os.makedirs(advs)
        uuid = "11111111-2222-3333-4444-555555555555"
        with open(os.path.join(inst.server_dir, "usercache.json"), "w") as fh:
            json.dump([{"name": "Steve", "uuid": uuid}, {"name": "Inconnu", "uuid": "zzz"}], fh)
        with open(os.path.join(stats, uuid + ".json"), "w") as fh:
            json.dump({"stats": {"minecraft:custom": {"minecraft:play_time": 72000, "minecraft:deaths": 4, "minecraft:walk_one_cm": 250000,
                                                        "minecraft:sprint_one_cm": 250000, "minecraft:jump": 10},
                                 "minecraft:mined": {"minecraft:stone": 30, "minecraft:dirt": 12}}}, fh)
        with open(os.path.join(advs, uuid + ".json"), "w") as fh:
            json.dump({"minecraft:story/root": {"done": True}, "minecraft:recipes/x": {"done": True}, "minecraft:story/y": {"done": False}, "DataVersion": 1}, fh)
        out = players.report(inst)
        steve = out["players"][0]
        self.assertTrue(steve["before_lana"])
        stats_by_key = {s["key"]: s["value"] for s in steve["stats"]}
        self.assertEqual(stats_by_key["playtime"], 3600)
        self.assertEqual(stats_by_key["deaths"], 4)
        self.assertEqual(stats_by_key["distance"], 5.0)
        self.assertEqual(stats_by_key["mined"], 42)
        self.assertEqual(stats_by_key["advancements"], 1)
        self.assertIn("Plus gros mineur", [r["label"] for r in out["records"]])

    def test_jeu_sans_suivi(self):
        inst = instances.Instance.create("fake")
        self.addCleanup(shutil.rmtree, inst.dir, True)
        inst._save_meta(dict(inst.meta(), installed=True))
        self.assertIsNone(players.report(inst))


class WebPayloadTests(unittest.TestCase):
    """Les réponses de l'API sont construites avec les vrais modules (un nom déplacé ailleurs casse ici)."""

    def test_payloads_de_l_api(self):
        self.assertTrue(web.games_payload())
        inst = instances.Instance.create("fake")
        self.addCleanup(shutil.rmtree, inst.dir, True)
        os.makedirs(inst.server_dir)
        config.write_initial(FAKE, inst.server_dir)
        inst._save_meta(dict(inst.meta(), installed=True))
        payload = web.instance_payload(inst)   # appelle aussi la détection de l'adresse locale
        self.assertEqual(payload["id"], inst.id)
        self.assertIn("connect", payload)


def fake_text_game(fmt, fields, **cfg):
    return {"id": "fake" + fmt, "config": dict({"file": "conf.txt", "format": fmt}, **cfg), "fields": fields}


class TextFormatsTests(unittest.TestCase):
    """Formats .ini, .cfg, xml et arma : relecture typée, réécriture qui garde le reste du fichier."""

    def roundtrip(self, game, content, changes):
        folder = tempfile.mkdtemp(prefix="lana-fmt-")
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "conf.txt"), "w", encoding="utf-8") as fh:
            fh.write(content)
        data = config.read_file(game, folder)
        before = dict(data)
        data.update(changes)
        config.write_file(game, folder, data)
        with open(os.path.join(folder, "conf.txt"), encoding="utf-8") as fh:
            return before, fh.read(), config.read_file(game, folder)

    def test_ini_a_sections(self):
        fields = [{"key": "[ServerSettings]XPMultiplier", "type": "float"}, {"key": "[ServerSettings]ServerPVE", "type": "bool"},
                  {"key": "[SessionSettings]SessionName", "type": "text"}, {"key": "[/Script/Engine.GameSession]MaxPlayers", "type": "int"}]
        before, text, after = self.roundtrip(fake_text_game("ini", fields),
            "; commentaire\n[ServerSettings]\nXPMultiplier=2.000000\nServerPVE=False\nInconnu=7\n[SessionSettings]\nSessionName=Ancien\n",
            {"[ServerSettings]ServerPVE": True, "[SessionSettings]SessionName": "Nouveau", "[/Script/Engine.GameSession]MaxPlayers": 12})
        self.assertEqual(before["[ServerSettings]XPMultiplier"], 2.0)
        self.assertIs(before["[ServerSettings]ServerPVE"], False)
        self.assertIn("; commentaire", text)
        self.assertIn("Inconnu=7", text)
        self.assertIn("ServerPVE=True", text)
        self.assertIn("[/Script/Engine.GameSession]\nMaxPlayers=12", text)
        self.assertEqual(after["[SessionSettings]SessionName"], "Nouveau")
        self.assertLess(text.index("ServerPVE=True"), text.index("[SessionSettings]"))

    def test_ini_cle_ajoutee_dans_sa_section(self):
        fields = [{"key": "[A]x", "type": "int"}, {"key": "[A]y", "type": "int"}]
        _b, text, _a = self.roundtrip(fake_text_game("ini", fields), "[A]\nx=1\n[B]\nz=2\n", {"[A]y": 5})
        self.assertLess(text.index("y=5"), text.index("[B]"))

    def test_cfg_source_et_prefixe(self):
        fields = [{"key": "hostname", "type": "text"}, {"key": "sv_lan", "type": "bool"}, {"key": "mp_timelimit", "type": "int"}]
        before, text, after = self.roundtrip(fake_text_game("cfg", fields),
            '// config\nhostname "Mon serveur" // nom\nsv_lan 0\nexec banned.cfg\n',
            {"hostname": "Autre nom", "sv_lan": True, "mp_timelimit": 25})
        self.assertEqual(before["hostname"], "Mon serveur")
        self.assertIs(before["sv_lan"], False)
        self.assertIn('hostname "Autre nom"', text)
        self.assertIn("sv_lan 1", text)
        self.assertIn("exec banned.cfg", text)
        self.assertEqual(after["mp_timelimit"], 25)
        _b, text, _a = self.roundtrip(fake_text_game("cfg", fields, prefix="set "), 'set hostname "A"\n', {"hostname": "B", "mp_timelimit": 9})
        self.assertIn('set hostname "B"', text)
        self.assertIn("set mp_timelimit 9", text)

    def test_cfg_sans_guillemets_unturned(self):
        fields = [{"key": "Name", "type": "text"}, {"key": "Port", "type": "int"}]
        before, text, _a = self.roundtrip(fake_text_game("cfg", fields, quote=False), "Name Mon serveur\nPort 27015\n", {"Name": "Autre serveur"})
        self.assertEqual(before["Name"], "Mon serveur")
        self.assertIn("Name Autre serveur\n", text)

    def test_xml_props_7dtd(self):
        fields = [{"key": "ServerName", "type": "text"}, {"key": "ServerPort", "type": "int"}]
        before, text, after = self.roundtrip(fake_text_game("xml_props", fields),
            '<?xml version="1.0"?>\n<ServerSettings>\n\t<property name="ServerName" value="Vieux"/>\t<!-- nom -->\n\t<property name="ServerPort" value="26900"/>\n</ServerSettings>\n',
            {"ServerName": "A & B", "UserDataFolder": "./UserData"})
        self.assertEqual(before["ServerPort"], 26900)
        self.assertIn('value="A &amp; B"', text)
        self.assertIn("<!-- nom -->", text)
        self.assertLess(text.index("UserDataFolder"), text.index("</ServerSettings>"))
        self.assertEqual(after["ServerName"], "A & B")

    def test_xml_elements_mta(self):
        fields = [{"key": "servername", "type": "text"}, {"key": "ase", "type": "bool"}]
        before, text, _a = self.roundtrip(fake_text_game("xml_elements", fields, bools=["1", "0"]),
            "<config>\n    <servername>Default MTA Server</servername>\n    <ase>1</ase>\n</config>\n", {"servername": "LANa", "ase": False})
        self.assertIs(before["ase"], True)
        self.assertIn("    <servername>LANa</servername>", text)
        self.assertIn("<ase>0</ase>", text)

    def test_arma_dayz(self):
        fields = [{"key": "hostname", "type": "text"}, {"key": "maxPlayers", "type": "int"}, {"key": "disable3rdPerson", "type": "bool"}]
        before, text, _a = self.roundtrip(fake_text_game("arma", fields),
            'hostname = "EXAMPLE";   // nom\nmaxPlayers = 60;\nmotd[] = {"a", "b"};\n', {"hostname": "LANa", "disable3rdPerson": True})
        self.assertEqual(before["maxPlayers"], 60)
        self.assertIn('hostname = "LANa";   // nom', text)
        self.assertIn('motd[] = {"a", "b"};', text)
        self.assertIn("disable3rdPerson = 1;", text)

    def test_format_none(self):
        game = fake_text_game("none", [])
        self.assertEqual(config.read_file(game, "/inexistant"), {})
        config.write_file(game, "/inexistant", {"x": 1})   # ne fait rien, ne lève rien


class InstallSourcesTests(unittest.TestCase):
    def test_resolution_des_telechargements(self):
        game = {"id": "x", "run": {"runtime": "wine", "command": ["a"]}, "install": {"source": {"kind": "bedrock"}}}
        original = runtime.fetch_json
        runtime.fetch_json = lambda url: {"result": {"links": [{"downloadType": "serverBedrockWindows", "downloadUrl": "W"},
                                                                {"downloadType": "serverBedrockLinux", "downloadUrl": "L"}]}}
        try:
            self.assertEqual(runtime.resolve_download(game), "W")   # serveur Windows (natif ou sous Wine)
            game["install"]["source"] = {"kind": "github", "repo": "o/r", "assets": {"windows": "win-x86.zip", "linux": "linux-x86.tar.gz"}}
            runtime.fetch_json = lambda url: {"assets": [{"name": "srv-linux-x86.tar.gz", "browser_download_url": "L"},
                                                         {"name": "srv-win-x86.zip", "browser_download_url": "W"}]}
            self.assertEqual(runtime.resolve_download(game), "W")
            game["install"]["source"] = {"kind": "url", "urls": {"linux": "only-linux"}}
            with self.assertRaises(RuntimeError):
                runtime.resolve_download(game)
            game["install"]["source"] = {"kind": "fxserver"}
            with self.assertRaises(RuntimeError):   # source retirée
                runtime.resolve_download(game)
        finally:
            runtime.fetch_json = original

    def test_fusion_sans_ecraser_la_config(self):
        src, dest = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, src, True)
        self.addCleanup(shutil.rmtree, dest, True)
        os.makedirs(os.path.join(src, "sub"))
        for rel, content in (("server.properties", "neuf"), ("bin", "neuf"), ("sub/a.txt", "neuf")):
            with open(os.path.join(src, rel), "w") as fh:
                fh.write(content)
        with open(os.path.join(dest, "server.properties"), "w") as fh:
            fh.write("réglages de l'utilisateur")
        runtime._merge_tree(src, dest, {"server.properties"})
        with open(os.path.join(dest, "server.properties")) as fh:
            self.assertEqual(fh.read(), "réglages de l'utilisateur")
        with open(os.path.join(dest, "sub", "a.txt")) as fh:
            self.assertEqual(fh.read(), "neuf")

    def test_variantes_linux_appliquees_au_chargement(self):
        game = {"id": "x", "run": {"runtime": "wine", "command": ["a.exe"], "linux": {"runtime": "native", "command": ["./a"]}},
                "install": {"check_file": "a.exe", "check_file_linux": "a"}, "config": {"file": "W/g.ini", "file_linux": "L/g.ini"},
                "savegame": "w", "savegame_linux": "l"}
        games.apply_platform(game)
        linux = system.IS_LINUX
        self.assertEqual(game["install"]["check_file"], "a" if linux else "a.exe")
        self.assertEqual(game["config"]["file"], "L/g.ini" if linux else "W/g.ini")
        self.assertEqual(game["savegame"], "l" if linux else "w")
        self.assertNotIn("check_file_linux", game["install"])
        self.assertEqual(games.run_spec(game)["command"], ["./a"] if linux else ["a.exe"])


UPLOAD_GAME = {
    "id": "fakeupload", "name": "Faux RAGE MP",
    "install": {"type": "upload", "check_file": "srv/ragemp-server.exe", "help": "Déposez l'archive", "keep": ["conf.json"]},
    "run": {"runtime": "native", "command": [sys.executable, "-c", "import time; time.sleep(300)"], "cwd": "."},
    "requirements": {"ram_gb_min": 1, "ram_gb_recommended": 1, "disk_gb": 1},
    "savegame": "packages",
    "config": {"file": "conf.json", "format": "json", "initial": {"name": "x", "bind": "0.0.0.0"}, "enforce": {"bind": "0.0.0.0"}},
    "fields": [{"key": "name", "label": "Nom", "type": "text", "default": "x", "group": "S"}],
}
games._cache["fakeupload"] = UPLOAD_GAME


class InstanceIdTests(unittest.TestCase):
    def test_identifiant_valide_pour_un_jeu_a_tiret_bas(self):
        games._cache["fake_jeu"] = dict(FAKE, id="fake_jeu")
        try:
            inst = instances.Instance.create("fake_jeu")
            self.addCleanup(shutil.rmtree, inst.dir, True)
            self.assertEqual(inst.id, "fake-jeu")
            self.assertEqual(inst.meta()["game"], "fake_jeu")
        finally:
            del games._cache["fake_jeu"]


class UploadInstallTests(unittest.TestCase):
    def make_zip(self, entries):
        folder = tempfile.mkdtemp(prefix="lana-up-")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "files.zip")
        with zipfile.ZipFile(path, "w") as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        return path

    def test_installation_par_archive(self):
        inst = instances.Instance.create("fakeupload")
        self.addCleanup(shutil.rmtree, inst.dir, True)
        with self.assertRaises(instances.InstanceError):
            inst.install()   # pas de téléchargement automatique pour ce jeu
        archive = self.make_zip({"server-files/srv/ragemp-server.exe": "exe", "server-files/conf.json": '{"name": "fourni"}'})
        inst.install_upload(archive, "files.zip")
        self.assertTrue(inst.meta()["installed"])
        self.assertTrue(os.path.exists(os.path.join(inst.server_dir, "srv", "ragemp-server.exe")))
        self.assertEqual(inst.read_config()["name"], "fourni")   # la config fournie est gardée
        self.assertEqual(config.read_file(inst.game, inst.server_dir)["bind"], "0.0.0.0")   # réglage imposé ajouté

    def test_archive_sans_le_serveur_refusee(self):
        inst = instances.Instance.create("fakeupload")
        self.addCleanup(shutil.rmtree, inst.dir, True)
        with self.assertRaises(instances.InstanceError):
            inst.install_upload(self.make_zip({"autre.txt": "x"}), "files.zip")
        with self.assertRaises(instances.InstanceError):
            inst.install_upload(self.make_zip({"../evil/srv/ragemp-server.exe": "x"}), "files.zip")
        self.assertFalse(inst.meta().get("installed"))


class StaticFilesTests(unittest.TestCase):
    def test_polices_servies(self):
        for name in ("inter", "space-grotesk", "jetbrains-mono"):
            found = web.static_file("/static/fonts/%s.woff2" % name)
            self.assertIsNotNone(found, name)
            self.assertEqual(found[1], "font/woff2")
            with open(found[0], "rb") as fh:
                self.assertEqual(fh.read(4), b"wOF2")

    def test_chemins_refuses(self):
        for bad in ("/static/../lana/web.py", "/static/fonts/../../lana/web.py", "/static/fonts/%2e%2e/x.woff2",
                    "/static//etc/passwd", "/static/fonts/OFL-inter.txt", "/static/fonts/inexistant.woff2",
                    "/static/fonts/inter.woff2/", "/static/Fonts/inter.woff2", "/web/index.html"):
            with self.subTest(path=bad):
                self.assertIsNone(web.static_file(bad))


class PlatformTests(unittest.TestCase):
    def test_meminfo_et_cpuinfo(self):
        self.assertEqual(system.parse_meminfo("MemTotal:        8040312 kB\nMemFree: 1 kB\n"), 8040312 * 1024)
        self.assertIsNone(system.parse_meminfo("rien"))
        self.assertEqual(system.parse_cpuinfo("processor\t: 0\nmodel name\t: Intel(R) Core(TM) i5\n"), "Intel(R) Core(TM) i5")

    def test_url_du_jre_selon_le_systeme(self):
        self.assertTrue(runtime.adoptium_url(21, mac=True, windows=False, machine_arch="x86_64").endswith("/21/ga/mac/x64/jre/hotspot/normal/eclipse"))
        self.assertIn("/ga/linux/aarch64/", runtime.adoptium_url(21, mac=False, windows=False, machine_arch="aarch64"))
        self.assertIn("/ga/windows/x64/", runtime.adoptium_url(21, mac=False, windows=True, machine_arch="AMD64"))

    def test_incompatibilite_limitee_a_une_plateforme(self):
        compat = {"level": "bad", "note": "n", "platforms": ["plateforme-inconnue"]}
        mach = {"ram_gb": 64, "disk_free_gb": 1000, "tools": {}}
        self.assertEqual(machine.verdict({}, [], mach, compat)["level"], "ok")
        self.assertEqual(machine.verdict({}, [], mach, dict(compat, platforms=[system.PLATFORM]))["level"], "bad")

    def test_wine_seulement_hors_windows(self):
        self.assertEqual(system.uses_wine("java"), False)
        self.assertEqual(system.uses_wine("wine"), not system.IS_WINDOWS)

    def test_detection_de_la_machine(self):
        info = machine.detect()
        self.assertTrue(info["os"])
        self.assertTrue(info["ram_gb"] is None or info["ram_gb"] > 0)

    def test_archive_zip_refuse_les_chemins_hors_destination(self):
        import zipfile
        folder = tempfile.mkdtemp(prefix="lana-zip-")
        try:
            archive = os.path.join(folder, "a.zip")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../evil.txt", "x")
            with self.assertRaises(RuntimeError):
                runtime._safe_extract(archive, os.path.join(folder, "out"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class UpnpTests(unittest.TestCase):
    DESC = b"""<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>
      <serviceList><service><serviceType>urn:schemas-upnp-org:service:Layer3Forwarding:1</serviceType>
      <controlURL>/ctl/L3F</controlURL></service></serviceList><deviceList><device><deviceList><device><serviceList>
      <service><serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
      <controlURL>/ctl/IPConn</controlURL></service></serviceList></device></deviceList></device></deviceList>
      </device></root>"""

    class FakeGateway:
        local_ip = "192.168.1.20"

        def __init__(self):
            self.table, self.fail = {}, {}

        def external_ip(self):
            return "88.120.4.7"

        def add(self, port, proto, description):
            if (port, proto) in self.fail:
                raise upnp.UPnPError("refus", self.fail[(port, proto)])
            self.table[(port, proto)] = description

        def delete(self, port, proto):
            self.table.pop((port, proto), None)

        def mappings(self):
            return [{"port": p, "proto": pr, "client": self.local_ip, "description": d} for (p, pr), d in self.table.items()]

    class FakeInstance:
        def __init__(self, inst_id, ports, running=True, enabled=True):
            self.id, self._ports, self.is_running, self.enabled = inst_id, ports, running, enabled

        def upnp_enabled(self):
            return self.enabled

        def meta(self):
            return {"installed": True}

        def running(self):
            return self.is_running

        def ports(self):
            return [{"port": p, "proto": pr, "label": ""} for p, pr in self._ports]

    def setUp(self):
        self.gw = self.FakeGateway()
        upnp._gateway, upnp._mapped, upnp._state, upnp._cleaned = self.gw, {}, {}, False

    def tearDown(self):
        upnp._gateway, upnp._mapped, upnp._state = None, {}, {}

    def test_parse_ssdp_and_description(self):
        reply = b"HTTP/1.1 200 OK\r\nST: x\r\nLocation: http://192.168.1.254:46409/rootDesc.xml\r\n\r\n"
        location = upnp.parse_ssdp(reply)
        self.assertEqual(location, "http://192.168.1.254:46409/rootDesc.xml")
        self.assertEqual(upnp.parse_description(self.DESC, location),
                         ("urn:schemas-upnp-org:service:WANIPConnection:1", "http://192.168.1.254:46409/ctl/IPConn"))

    def test_soap(self):
        body = upnp.soap_body("urn:x", "AddPortMapping", [("NewPortMappingDescription", "a<b&c")])
        self.assertIn(b"<NewPortMappingDescription>a&lt;b&amp;c</NewPortMappingDescription>", body)
        ok = b"""<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
          <u:GetExternalIPAddressResponse xmlns:u="urn:x"><NewExternalIPAddress>88.120.4.7</NewExternalIPAddress>
          </u:GetExternalIPAddressResponse></s:Body></s:Envelope>"""
        self.assertEqual(upnp.parse_soap(ok), {"NewExternalIPAddress": "88.120.4.7"})
        fault = b"""<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault><detail>
          <UPnPError xmlns="urn:schemas-upnp-org:control-1-0"><errorCode>718</errorCode>
          <errorDescription>ConflictInMappingEntry</errorDescription></UPnPError></detail></s:Fault></s:Body></s:Envelope>"""
        with self.assertRaises(upnp.UPnPError) as ctx:
            upnp.parse_soap(fault)
        self.assertEqual(ctx.exception.code, 718)

    def test_sync_opens_and_closes(self):
        inst = self.FakeInstance("valheim", [(2456, "udp"), (2457, "udp")])
        upnp.sync([inst])
        self.assertEqual(self.gw.table, {(2456, "udp"): "LANa valheim", (2457, "udp"): "LANa valheim"})
        status = upnp.status(inst)
        self.assertEqual((status["state"], status["external_ip"]), ("ok", "88.120.4.7"))
        inst.is_running = False
        upnp.sync([inst])
        self.assertEqual(self.gw.table, {})
        self.assertEqual(upnp.status(inst)["state"], "off")

    def test_disabled_and_conflict(self):
        off = self.FakeInstance("mc", [(25565, "tcp")], enabled=False)
        busy = self.FakeInstance("rust", [(28015, "udp")])
        self.gw.fail[(28015, "udp")] = upnp.CONFLICT
        upnp.sync([off, busy])
        self.assertEqual(self.gw.table, {})
        self.assertFalse(upnp.status(off)["enabled"])
        self.assertIn("autre machine", upnp.status(busy)["message"])

    def test_leftovers_removed(self):
        self.gw.table = {(9999, "udp"): "LANa ancien", (8080, "tcp"): "autre logiciel"}
        upnp.sync([self.FakeInstance("cs2", [(27015, "udp")])])
        self.assertEqual(set(self.gw.table), {(27015, "udp"), (8080, "tcp")})

    def test_private_external_ip_warns(self):
        self.gw.external_ip = lambda: "100.64.3.2"   # CGNAT
        inst = self.FakeInstance("cs2", [(27015, "udp")])
        upnp.sync([inst])
        self.assertEqual(upnp.status(inst)["state"], "error")
        self.assertIn("CGNAT", upnp.status(inst)["message"])

    def test_every_game_port_is_mappable(self):
        for game_id, game in games.load_all().items():
            keys = {f["key"] for f in game["fields"]}
            for port in game.get("ports", []):
                self.assertIn(port["proto"], ("tcp", "udp"), game_id)
                self.assertIn(port["from"], keys, game_id)


class VersionTests(unittest.TestCase):
    def test_minecraft_releases_only_down_to_first_server(self):
        manifest = {"versions": [{"id": "1.21.9", "type": "release", "releaseTime": "2026-09-30T10:00:00+00:00"},
                                 {"id": "25w40a", "type": "snapshot"}, {"id": "1.2.5", "type": "release"},
                                 {"id": "1.2.4", "type": "release"}]}
        found = versions.parse_minecraft(manifest)
        self.assertEqual([v["id"] for v in found], ["1.21.9", "1.2.5"])
        self.assertIsNotNone(found[0]["date"])

    def test_steam_branches(self):
        info = {"data": {"7": {"depots": {"branches": {
            "alpha20.7": {"description": "Alpha 20.7 Stable", "timeupdated": "1681834192"},
            "public": {"timeupdated": "1793638791"},
            "secret": {"pwdrequired": "1", "timeupdated": "1793638792"},
            "default_old": {"description": "\tPrevious stable", "timeupdated": "1790000000"},
            "+quit": {"timeupdated": "1"}}}}}}
        found = versions.parse_steam(info, 7)
        self.assertEqual([v["id"] for v in found], ["public", "default_old", "alpha20.7"])   # publique d'abord, puis la plus récente
        self.assertEqual(found[1]["label"], "default_old — Previous stable")

    def test_github_releases(self):
        found = versions.parse_github([{"tag_name": "v1.6", "prerelease": True}, {"tag_name": "v1.5", "draft": True},
                                       {"tag_name": "v1.4", "published_at": "2025-01-02T03:04:05Z"}])
        self.assertEqual([v["label"] for v in found], ["v1.6 (préversion)", "v1.4"])

    def test_kind_and_check(self):
        folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "games")
        get = lambda name: json.load(open(os.path.join(folder, name + ".json"), encoding="utf-8"))
        self.assertEqual(versions.kind(get("valheim")), "steam")
        self.assertEqual(versions.kind(get("minecraft")), "minecraft")
        self.assertEqual(versions.kind(get("openmp")), "github")
        self.assertIsNone(versions.kind(get("minecraft_bedrock")))
        self.assertIsNone(versions.kind(get("ragemp")))
        for bad in ("+quit", "a b", "-beta", ""):
            with self.assertRaises(versions.VersionError):
                versions.check(get("valheim"), bad)

    def test_github_tag_download_url(self):
        game = {"id": "x", "run": {"runtime": "wine", "command": ["a"]},
                "install": {"source": {"kind": "github", "repo": "o/r", "assets": {"windows": "win.zip"}}}}
        seen, original = [], runtime.fetch_json
        runtime.fetch_json = lambda url: seen.append(url) or {"assets": [{"name": "s-win.zip", "browser_download_url": "W"}]}
        try:
            runtime.resolve_download(game, "v1.4")
            runtime.resolve_download(game)
        finally:
            runtime.fetch_json = original
        self.assertEqual(seen, ["https://api.github.com/repos/o/r/releases/tags/v1.4", "https://api.github.com/repos/o/r/releases/latest"])

    def test_install_keeps_chosen_branch(self):
        games._cache["fakesteam"] = dict(FAKE, id="fakesteam", install={"type": "steamcmd", "appid": 1, "check_file": "x"})
        branches, original = [], runtime.steamcmd_install
        runtime.steamcmd_install = lambda game, d, p, job, branch=None: branches.append(branch)

        def run(job):
            while job.state == "running":
                time.sleep(0.01)
            self.assertEqual(job.state, "done", job.lines)
        try:
            inst = instances.Instance.create("fakesteam")
            run(inst.install(version="alpha20.7"))
            run(inst.install())   # « Réessayer », mise à jour : même branche
            save = os.path.join(inst.server_dir, "save")
            os.makedirs(save)
            inst.start()
            with self.assertRaises(instances.InstanceError):
                inst.change_version("public")
            inst.stop(backup=False)
            run(inst.change_version("public"))
            self.assertTrue(any("avant-version" in b["name"] for b in inst.backups()))
            with self.assertRaises(instances.InstanceError):
                inst.install(version="+quit")
        finally:
            runtime.steamcmd_install = original
            del games._cache["fakesteam"]
        self.assertEqual(branches, ["alpha20.7", "alpha20.7", "public"])
        self.assertEqual(inst.meta()["version"], "public")


def _wait_job(test, job):
    while job.state == "running":
        time.sleep(0.01)
    test.assertEqual(job.state, "done", job.lines)


class ModsTests(unittest.TestCase):
    def setUp(self):
        self.patched = []

    def tearDown(self):
        for obj, name, old in reversed(self.patched):
            setattr(obj, name, old)
        for gid in ("fakemc", "fakets", "fakews"):
            games._cache.pop(gid, None)

    def patch(self, obj, name, value):
        self.patched.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def make(self, gid, game_mods, **extra):
        games._cache[gid] = dict(FAKE, id=gid, mods=game_mods, **extra)
        inst = instances.Instance.create(gid)
        os.makedirs(inst.server_dir)
        inst._save_meta(dict(inst.meta(), installed=True, version="1.21.4"))
        return inst

    def test_definitions(self):
        folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "games")
        seen = 0
        for name in os.listdir(folder):
            game = json.load(open(os.path.join(folder, name), encoding="utf-8"))
            spec = game.get("mods")
            if not spec:
                continue
            seen += 1
            self.assertIn(spec["provider"], mods.PROVIDER_LABELS, name)
            if spec["provider"] == "thunderstore":
                self.assertTrue(spec["community"] and spec["loader"] and spec["dir"], name)
            if spec["provider"] == "workshop":
                self.assertTrue(spec["appid"] and spec["targets"], name)
        self.assertGreaterEqual(seen, 7)

    def test_thunderstore_layouts(self):
        def plan(names):
            path = os.path.join(_home, "t.zip")
            with zipfile.ZipFile(path, "w") as zf:
                for n in names:
                    zf.writestr(n, "x")
            members = mods._zip_members(path)
            m = mods._thunderstore_mapping(members, "A-B")
            return [m(n) for n in names]
        self.assertEqual(plan(["manifest.json", "icon.png", "B.dll"]), [None, None, "BepInEx/plugins/A-B/B.dll"])
        self.assertEqual(plan(["plugins/B.dll", "config/b.cfg"]), ["BepInEx/plugins/A-B/B.dll", "BepInEx/config/b.cfg"])
        self.assertEqual(plan(["BepInEx/plugins/B.dll", "README.md"]), ["BepInEx/plugins/B.dll", None])

    def test_zip_paths_are_checked(self):
        path = os.path.join(_home, "evil.zip")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("../../x.dll", "x")
        with self.assertRaises(mods.ModError):
            mods._zip_members(path)
        with self.assertRaises(mods.ModError):
            mods._inside(_home, "../x")

    def test_modrinth_install_with_dependency(self):
        inst = self.make("fakemc", {"provider": "modrinth"})
        inst._save_meta(dict(inst.meta(), mc_loader="fabric"))
        versions_of = {
            "AAA": [{"id": "v1", "version_number": "1.0", "version_type": "release",
                     "files": [{"filename": "a-1.0.jar", "primary": True, "url": "u/a", "hashes": {}}],
                     "dependencies": [{"project_id": "BBB", "dependency_type": "required"}]}],
            "BBB": [{"id": "v2", "version_number": "2.0", "version_type": "release",
                     "files": [{"filename": "b-2.0.jar", "primary": True, "url": "u/b", "hashes": {}}], "dependencies": []}]}

        def fetch(url):
            proj = url.split("/project/")[1].split("/")[0].split("?")[0]
            return versions_of[proj] if "/version" in url else {"title": proj, "project_type": "mod", "slug": proj}
        self.patch(runtime, "fetch_json", fetch)
        self.patch(runtime, "download", lambda url, dest, job, label, sha1=None: open(dest, "w").write(url))
        _wait_job(self, mods.install(inst, "AAA"))
        st = mods.state(inst)
        self.assertEqual(sorted(os.listdir(os.path.join(inst.server_dir, "mods"))), ["a-1.0.jar", "b-2.0.jar"])
        self.assertEqual(next(e for e in st["entries"] if e["project"] == "BBB")["required_by"], ["modrinth:AAA"])
        with self.assertRaises(mods.ModError):
            mods.remove(inst, "modrinth:BBB")   # encore nécessaire à AAA
        mods.toggle(inst, "modrinth:AAA", False)
        self.assertEqual(os.listdir(os.path.join(inst.server_dir, "mods")), ["b-2.0.jar"])
        mods.toggle(inst, "modrinth:AAA", True)
        mods.remove(inst, "modrinth:AAA")
        mods.remove(inst, "modrinth:BBB")
        self.assertEqual(os.listdir(os.path.join(inst.server_dir, "mods")), [])
        # moteur : le .jar remplace server.jar au lancement seulement s'il est là
        self.assertEqual(mods.launch_overrides(inst)["replace"], {})
        open(os.path.join(inst.server_dir, "fabric-server-launch.jar"), "w").close()
        self.assertEqual(mods.launch_overrides(inst)["replace"], {"server.jar": "fabric-server-launch.jar"})

    def test_manual_upload_found_files_and_configs(self):
        inst = self.make("fakets", {"provider": "thunderstore", "community": "x", "loader": "L-P", "dir": "BepInEx/plugins",
                                    "extensions": [".dll", ".zip"], "config_dirs": ["BepInEx/config"]})
        src = os.path.join(_home, "Mine.dll")
        open(src, "w").write("dll")
        with self.assertRaises(mods.ModError):
            mods.upload(inst, src, "Mine.exe")
        mods.upload(inst, src, "Mine.dll")
        archive = os.path.join(_home, "Pack.zip")
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("plugins/P.dll", "p")
            zf.writestr("config/p.cfg", "a=1")
        mods.upload(inst, archive, "Pack.zip")
        write(os.path.join(inst.server_dir, "BepInEx", "plugins", "Copied.dll"), "c")
        st = mods.state(inst)
        self.assertEqual([e["name"] for e in st["entries"]], ["Mine.dll", "Pack.zip"])
        self.assertEqual([f["name"] for f in st["found"]], ["Copied.dll"])
        self.assertEqual(st["config_files"], ["BepInEx/config/p.cfg"])
        mods.toggle(inst, "found:BepInEx/plugins/Copied.dll", False)
        self.assertFalse(os.path.exists(os.path.join(inst.server_dir, "BepInEx", "plugins", "Copied.dll")))
        self.assertEqual(mods.read_config(inst, "BepInEx/config/p.cfg"), "a=1")
        mods.write_config(inst, "BepInEx/config/p.cfg", "a=2")
        self.assertEqual(mods.read_config(inst, "BepInEx/config/p.cfg"), "a=2")
        for bad in ("../instance.json", "BepInEx/plugins/Mine.dll", "/etc/hosts"):
            with self.assertRaises(mods.ModError):
                mods.read_config(inst, bad)
        mods.remove(inst, "manual:Pack.zip")
        self.assertFalse(os.path.exists(os.path.join(inst.server_dir, "BepInEx", "plugins", "Pack")))
        self.assertEqual(mods.launch_overrides(inst)["env"], {})   # pas de BepInEx posé : rien à forcer dans Wine

    def test_workshop_targets_keep_manual_values(self):
        spec = {"provider": "workshop", "appid": 108600, "mod_ids": True,
                "targets": [{"key": "WorkshopItems", "sep": ";", "what": "items"},
                            {"key": "Mods", "sep": ";", "what": "mod_ids", "prefix_pz": True},
                            {"key": "[ServerSettings]ActiveMods", "sep": ",", "what": "items", "file": "Game.ini"},
                            {"file": "W.json", "json_list": "File_IDs", "what": "items"}], "args": ["-auto"]}
        inst = self.make("fakews", spec)
        write(os.path.join(inst.server_dir, "cfg.json"), "WorkshopItems=111\nMods=\\Hand\nOther=1\n")
        write(os.path.join(inst.server_dir, "Game.ini"), "[ServerSettings]\nX=1\n")
        details = [{"result": 1, "publishedfileid": "2392709985", "consumer_app_id": 108600, "title": "Lib",
                    "description": "Workshop ID: 2392709985\nMod ID: tsarslib"}]
        self.patch(mods, "_get_json", lambda url, data=None: {"response": {"publishedfiledetails": details}} if "Details" in url
                   else {"response": {"collectiondetails": [{"publishedfileid": "2392709985", "result": 9}]}})
        self.assertEqual(mods.launch_overrides(inst)["args"], [])
        mods.install(inst, "https://steamcommunity.com/sharedfiles/filedetails/?id=2392709985")
        text = read(os.path.join(inst.server_dir, "cfg.json"))
        self.assertIn("WorkshopItems=111;2392709985", text)
        self.assertIn("Mods=\\Hand;\\tsarslib", text)
        self.assertIn("Other=1", text)
        self.assertEqual(read(os.path.join(inst.server_dir, "Game.ini")), "[ServerSettings]\nX=1\nActiveMods=2392709985\n")
        self.assertEqual(json.load(open(os.path.join(inst.server_dir, "W.json")))["File_IDs"], [2392709985])
        self.assertEqual(mods.launch_overrides(inst)["args"], ["-auto"])
        inst._save_meta(dict(inst.meta(), version="legacy41"))   # Build 41 : identifiants sans « \ »
        mods.set_mod_ids(inst, "workshop:2392709985", ["tsarslib", "other"])
        self.assertIn("Mods=\\Hand;tsarslib;other", read(os.path.join(inst.server_dir, "cfg.json")))
        mods.remove(inst, "workshop:2392709985")
        text = read(os.path.join(inst.server_dir, "cfg.json"))
        self.assertIn("WorkshopItems=111\n", text)
        self.assertIn("Mods=\\Hand\n", text)

    def test_workshop_ids_parsing(self):
        self.assertEqual(mods._parse_workshop_ids("https://steamcommunity.com/sharedfiles/filedetails/?id=2392709985&x=1 731604991"),
                         ["2392709985", "731604991"])
        self.assertEqual(mods._parse_workshop_ids("bonjour"), [])
        self.assertEqual(mods._strip_bbcode("[img]https://x/y.png[/img] [h1]Salut[/h1] voir https://a.b/c"), "Salut voir")


if __name__ == "__main__":
    unittest.main()
