using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace DesktopGremlin
{
    /// <summary>
    /// 与本地 Ollama 通信的最小客户端。刻意不引第三方 JSON 库。
    /// </summary>
    public static class OllamaClient
    {
        public const string Endpoint = "http://127.0.0.1:11434";
        public const string Model = "qwen9b";
        public const bool Think = false;
        public const int NumPredict = 1536;
        public const int HistoryRounds = 8;

        public static void ChatStream(
            List<Dictionary<string, object>> messages,
            Action<string> onDelta,
            Action onDone,
            Action<string> onError)
        {
            Thread t = new Thread(delegate ()
            {
                try
                {
                    var payload = new Dictionary<string, object>();
                    payload["model"] = Model;
                    payload["messages"] = messages;
                    payload["stream"] = true;
                    payload["think"] = Think;

                    var options = new Dictionary<string, object>();
                    options["num_predict"] = NumPredict;
                    payload["options"] = options;

                    var js = new JavaScriptSerializer();
                    byte[] body = Encoding.UTF8.GetBytes(js.Serialize(payload));

                    var req = (HttpWebRequest)WebRequest.Create(Endpoint + "/api/chat");
                    req.Method = "POST";
                    req.ContentType = "application/json";
                    req.Proxy = null;              // 关键：绕过系统代理（Clash 会把 127.0.0.1 也代理掉）
                    req.Timeout = 300000;
                    req.ReadWriteTimeout = 300000;

                    using (Stream rs = req.GetRequestStream())
                    {
                        rs.Write(body, 0, body.Length);
                    }

                    using (var resp = (HttpWebResponse)req.GetResponse())
                    using (var sr = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                    {
                        string line;
                        while ((line = sr.ReadLine()) != null)
                        {
                            if (line.Length == 0) continue;

                            Dictionary<string, object> obj;
                            try { obj = js.Deserialize<Dictionary<string, object>>(line); }
                            catch { continue; }

                            object errObj;
                            if (obj.TryGetValue("error", out errObj))
                            {
                                onError(Convert.ToString(errObj));
                                return;
                            }

                            object msgObj;
                            if (obj.TryGetValue("message", out msgObj))
                            {
                                var m = msgObj as Dictionary<string, object>;
                                if (m != null && m.ContainsKey("content"))
                                {
                                    string piece = Convert.ToString(m["content"]);
                                    if (!string.IsNullOrEmpty(piece)) onDelta(piece);
                                }
                            }

                            object doneObj;
                            if (obj.TryGetValue("done", out doneObj) && Convert.ToBoolean(doneObj))
                            {
                                break;
                            }
                        }
                    }

                    onDone();
                }
                catch (Exception ex)
                {
                    onError(ex.Message);
                }
            });
            t.IsBackground = true;
            t.Start();
        }
    }
}
