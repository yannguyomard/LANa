// LANa.exe : lance l'appli de bureau (python\python.exe -m desktop) sans fenêtre de console.
// Compilé par build.ps1 avec le csc.exe du .NET Framework 4, présent sur tous les Windows (C# 5).
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

// Informations de version complètes (visibles dans Propriétés > Détails) : un exécutable anonyme est plus souvent
// pris pour suspect par les antivirus. Version remplacée par build.ps1 (celle de lana/__init__.py).
[assembly: AssemblyTitle("LANa")]
[assembly: AssemblyProduct("LANa")]
[assembly: AssemblyDescription("LANa - serveurs de jeu pour vos amis (lanceur de l'appli de bureau)")]
[assembly: AssemblyCompany("LANa (logiciel libre, licence MIT)")]
[assembly: AssemblyCopyright("Yann Guyomard - licence MIT - github.com/yannguyomard/LANa")]
[assembly: AssemblyVersion("0.0.0.0")]
[assembly: AssemblyFileVersion("0.0.0.0")]

static class Program
{
    [STAThread]
    static int Main()
    {
        string root = Path.GetDirectoryName(Application.ExecutablePath);
        string python = Path.Combine(root, "python", "python.exe");
        string app = Path.Combine(root, "app");
        if (!File.Exists(python) || !Directory.Exists(Path.Combine(app, "desktop")))
        {
            MessageBox.Show("Fichiers de LANa introuvables à côté de LANa.exe (dossiers python et app).\n" +
                            "Décompressez à nouveau l'archive complète.", "LANa", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        var psi = new ProcessStartInfo(python, "-X utf8 -m desktop");
        psi.WorkingDirectory = app;
        psi.UseShellExecute = false;
        // Console cachée plutôt que pythonw : les serveurs de jeu lancés par LANa en héritent, aucune fenêtre
        // noire ne s'ouvre, et LANa peut leur envoyer Ctrl+Pause pour les arrêter proprement (avec sauvegarde).
        psi.CreateNoWindow = true;
        psi.EnvironmentVariables["LANA_APP_LOG"] = "1";   // sortie et erreurs dans %USERPROFILE%\LANa\appli.log
        Process proc;
        try
        {
            proc = Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("Impossible de lancer LANa : " + ex.Message, "LANa", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        // Une appli qui s'arrête tout de suite en erreur (fichier manquant, Windows trop ancien…) ne montrerait
        // rien : on le signale, avec le journal.
        if (proc.WaitForExit(6000) && proc.ExitCode != 0)
        {
            string home = Environment.GetEnvironmentVariable("LANA_HOME");
            if (string.IsNullOrEmpty(home))
                home = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "LANa");
            MessageBox.Show("LANa n'a pas pu démarrer (code " + proc.ExitCode + ").\n\nLe détail est dans :\n" +
                            Path.Combine(home, "appli.log"), "LANa", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return proc.ExitCode;
        }
        return 0;
    }
}
