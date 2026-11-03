/* LANa.app : lanceur de l'appli de bureau (desktop/, Qt) avec le Python embarqué.
 *
 * Le programme principal de l'app reste ce lanceur, et non python3 : macOS affiche alors le nom
 * et l'icône de LANa (menu, Dock). Il charge la bibliothèque Python de l'architecture qui tourne
 * (Intel ou Apple Silicon) et lui fait exécuter « python -m desktop » depuis la copie de LANa embarquée.
 */
#include <dlfcn.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#if defined(__arm64__)
#define PYTHON_DIR "python-arm64"
#else
#define PYTHON_DIR "python-x86_64"
#endif

static void fail(const char *what, const char *detail) {
    fprintf(stderr, "LANa : %s (%s)\n", what, detail ? detail : "");
    exit(1);
}

int main(int argc, char **argv) {
    char exe[PATH_MAX], real[PATH_MAX], rel[PATH_MAX], res[PATH_MAX], home[PATH_MAX], lib[PATH_MAX], app[PATH_MAX], path[PATH_MAX * 2];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real)) fail("chemin introuvable", NULL);
    char *slash = strrchr(real, '/');               /* …/LANa.app/Contents/MacOS/LANa */
    *slash = '\0';
    snprintf(rel, sizeof(rel), "%s/../Resources", real);
    if (!realpath(rel, res)) fail("dossier Resources introuvable", rel);
    snprintf(home, sizeof(home), "%s/%s", res, PYTHON_DIR);
    snprintf(lib, sizeof(lib), "%s/lib/libpython3.12.dylib", home);
    snprintf(app, sizeof(app), "%s/LANa", res);
    snprintf(path, sizeof(path), "%s/site-packages:%s", res, app);

    setenv("PYTHONHOME", home, 1);
    setenv("PYTHONPATH", path, 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);      /* rien n'est écrit dans l'app : sa signature reste valide */
    setenv("PYTHONNOUSERSITE", "1", 1);
    unsetenv("PYTHONSTARTUP");
    if (chdir(app) != 0) fail("dossier de LANa introuvable", app);

    void *py = dlopen(lib, RTLD_NOW | RTLD_GLOBAL);  /* RTLD_GLOBAL : les modules (PySide6…) y trouvent Python */
    if (!py) fail("Python embarqué illisible", dlerror());
    int (*bytes_main)(int, char **) = (int (*)(int, char **))dlsym(py, "Py_BytesMain");
    if (!bytes_main) fail("Python embarqué incomplet", dlerror());

    char *args[] = {argv[0], "-m", "desktop", NULL};
    (void)argc;
    return bytes_main(3, args);
}
