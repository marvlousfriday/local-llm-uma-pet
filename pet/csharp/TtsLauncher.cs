using System;
using System.Diagnostics;
using System.IO;
using System.Net;

namespace DesktopGremlin
{
    /// <summary>
    /// 随桌宠启动 / 关闭本地 TTS 服务。
    /// 只接管"自己启动的"进程；如果服务已经在跑（用户手动启动），退出时不会去杀。
    /// </summary>
    public static class TtsLauncher
    {
        private static readonly object _Gate = new object();
        private static Process _proc;

        private static void Log(string msg)
        {
            try
            {
                File.AppendAllText(
                    Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "tts_launcher.log"),
                    DateTime.Now.ToString("HH:mm:ss") + " " + msg + Environment.NewLine);
            }
            catch { }
        }

        /// <summary>
        /// 桌宠角色目录名 -> VITS 模型目录名。
        /// 新角色只要模型目录同名即可自动生效；Doto 是历史目录名，映射到 MeishoDoto。
        /// 模型不存在时回退 MeishoDoto，避免服务起不来。
        /// </summary>
        private static string TtsModelName(string script)
        {
            string ch = Settings.StartingChar;
            if (string.IsNullOrEmpty(ch)) return "MeishoDoto";
            string model = ch.Equals("Doto", StringComparison.OrdinalIgnoreCase)
                ? "MeishoDoto" : ch;
            string dir = Path.Combine(Path.GetDirectoryName(script) ?? "", "models", model);
            if (!Directory.Exists(dir))
            {
                Log("找不到音色模型 " + dir + "，回退 MeishoDoto");
                return "MeishoDoto";
            }
            return model;
        }

        public static void EnsureRunning()
        {
            string py = Settings.TtsPython;
            string script = Settings.TtsScript;
            Log("EnsureRunning py=" + (py ?? "(null)") + " script=" + (script ?? "(null)"));

            if (string.IsNullOrEmpty(py) || string.IsNullOrEmpty(script))
            {
                Log("配置为空，跳过");
                return;
            }
            if (!File.Exists(py)) { Log("找不到 python: " + py); return; }
            if (!File.Exists(script)) { Log("找不到脚本: " + script); return; }

            lock (_Gate)
            {
                if (_proc != null && !_proc.HasExited) return;
                if (Ping())
                {
                    Log("已有服务在跑，不接管");
                    return;
                }

                try
                {
                    var psi = new ProcessStartInfo();
                    psi.FileName = py;
                    psi.Arguments = "\"" + script + "\" --port 9880 --idle " +
                                    (Settings.TtsIdle > 0 ? Settings.TtsIdle : 1800) +
                                    " --char \"" + TtsModelName(script) + "\"" +
                                    " --parent-pid " + Process.GetCurrentProcess().Id;
                    psi.WorkingDirectory = Path.GetDirectoryName(script);
                    psi.UseShellExecute = false;
                    psi.CreateNoWindow = true;
                    _proc = Process.Start(psi);
                    Log("已启动 PID=" + (_proc != null ? _proc.Id.ToString() : "null"));
                }
                catch (Exception ex)
                {
                    Log("启动失败: " + ex.Message);
                    _proc = null;
                }
            }
        }

        /// <summary>探测服务是否已就绪</summary>
        public static bool Ping(int timeoutMs = 1200)
        {
            try
            {
                var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:9880/health");
                req.Proxy = null;
                req.Timeout = timeoutMs;
                req.ReadWriteTimeout = timeoutMs;
                using (var resp = (HttpWebResponse)req.GetResponse())
                {
                    return resp.StatusCode == HttpStatusCode.OK;
                }
            }
            catch
            {
                return false;
            }
        }

        public static void Stop()
        {
            lock (_Gate)
            {
                Process p = _proc;
                _proc = null;
                if (p == null) return;

                try
                {
                    if (p.HasExited) return;

                    // venv 的 pythonw 只是启动器，真正的解释器是它的子进程。
                    // 直接 Kill 会留下孤儿占着 9880 端口，必须连进程树一起杀。
                    var psi = new ProcessStartInfo();
                    psi.FileName = "taskkill";
                    psi.Arguments = "/PID " + p.Id + " /T /F";
                    psi.UseShellExecute = false;
                    psi.CreateNoWindow = true;
                    using (Process killer = Process.Start(psi))
                    {
                        if (killer != null) killer.WaitForExit(3000);
                    }
                }
                catch
                {
                }
            }
        }
    }
}
