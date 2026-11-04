using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using System.Globalization;
using System.Media;
using System.Net;
using System.Threading;
using System.Text.RegularExpressions;

namespace DesktopGremlin
{
    public partial class ChatWindow : Window
    {
        private readonly List<Dictionary<string, object>> _history = new List<Dictionary<string, object>>();
        private readonly StringBuilder _pending = new StringBuilder();
        private bool _busy;
        private TextBlock _streamTarget;

        private static readonly Brush AssistantBg = Brushes.White;
        private static readonly Brush AssistantBorder = new SolidColorBrush(Color.FromRgb(0xF7, 0xCE, 0xE0));
        private static readonly Brush AssistantText = new SolidColorBrush(Color.FromRgb(0x4A, 0x2E, 0x3A));
        private static readonly Brush UserBg = new SolidColorBrush(Color.FromRgb(0xFF, 0xDC, 0xEA));
        private static readonly Brush UserText = new SolidColorBrush(Color.FromRgb(0x5A, 0x2C, 0x40));

        private const string DefaultPersona =
            "你是特雷萨学园的马娘「名将怒涛」（メイショウドトウ），正趴在训练员的桌面上陪他。\n" +
            "性格：内向、谦虚、容易紧张，缺乏自信但非常努力；被夸奖会慌乱地否认，说话常带「あの…」「えっと…」这类迟疑。\n" +
            "语气：温柔、礼貌，偶尔小声抱怨，但绝不说重话。\n" +
            "格式要求（必须遵守）：\n" +
            "每次回复严格两行，不要空行。\n" +
            "第一行以 [中] 开头，写中文回答，不超过 30 字。\n" +
            "第二行以 [日] 开头，写这句中文对应的日语口语说法，像动画台词，不超过 30 字。\n" +
            "不要自称 AI、不要提模型、不要用列表、标题或 emoji。";

        private static string _persona = DefaultPersona;

        /// <summary>
        /// 从程序目录的 persona.txt 读取人设，没有就用内置默认。
        /// 注意：必须保留 [中]/[日] 两行格式约定，否则程序无法拆分显示与朗读。
        /// </summary>
        private static void LoadPersona()
        {
            try
            {
                string path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "persona.txt");
                if (!File.Exists(path)) return;

                string text = File.ReadAllText(path).Trim();
                if (text.Length < 20) return;
                if (!text.Contains("[中]") || !text.Contains("[日]")) return;   // 缺格式约定就忽略，避免不朗读

                // 去掉 # 开头的注释行，别把注释当 prompt 发出去
                var sb = new StringBuilder();
                foreach (string line in File.ReadAllLines(path))
                {
                    if (line.TrimStart().StartsWith("#")) continue;
                    sb.AppendLine(line);
                }
                string clean = sb.ToString().Trim();
                if (clean.Length >= 20) _persona = clean;
            }
            catch
            {
            }
        }

        private DispatcherTimer _followTimer;
        private double _lastOwnerLeft = double.NaN;
        private double _lastOwnerTop = double.NaN;

        private SoundPlayer _player;
        private MemoryStream _playerStream;
        private const string TtsUrl = "http://127.0.0.1:9880";
        private const double TtsSpeed = 1.0;

        public ChatWindow()
        {
            InitializeComponent();
            LoadAvatar();
            LoadPersona();
            Loaded += delegate { Input.Focus(); };
        }

        private void SetCharName(string folder)
        {
            if (NameText == null) return;
            NameText.Text = string.IsNullOrEmpty(folder) ? "马娘" : folder;
        }

        /// <summary>
        /// 从当前角色的 idle.png 里裁一张头像：取第一格 → 按 alpha 找内容边界 → 裁头部方形区域。
        /// 找不到就保留「马」字占位。
        /// </summary>
        private void LoadAvatar()
        {
            try
            {
                string ch = Settings.StartingChar;
                SetCharName(ch);
                string path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory,
                    "SpriteSheet", "Gremlins", ch, "Actions", "idle.png");
                if (!File.Exists(path)) return;

                var src = new BitmapImage();
                src.BeginInit();
                src.UriSource = new Uri(path, UriKind.Absolute);
                src.CacheOption = BitmapCacheOption.OnLoad;
                src.EndInit();

                int cell = src.PixelWidth / 10;
                if (cell <= 0) return;
                cell = Math.Min(cell, src.PixelHeight);

                var cellBmp = new CroppedBitmap(src, new Int32Rect(0, 0, cell, cell));

                // 统一成 BGRA32，避免索引色 PNG 的步长计算错误
                var conv = new FormatConvertedBitmap(cellBmp, PixelFormats.Bgra32, null, 0);

                // 扫描 alpha 找内容包围盒
                int stride = conv.PixelWidth * 4;
                byte[] px = new byte[stride * conv.PixelHeight];
                conv.CopyPixels(px, stride, 0);

                int minX = cell, minY = cell, maxX = -1, maxY = -1;
                for (int y = 0; y < cell; y++)
                {
                    int row = y * stride;
                    for (int x = 0; x < cell; x++)
                    {
                        if (px[row + x * 4 + 3] <= 16) continue;
                        if (x < minX) minX = x;
                        if (x > maxX) maxX = x;
                        if (y < minY) minY = y;
                        if (y > maxY) maxY = y;
                    }
                }
                if (maxX < 0) return;

                int h = maxY - minY;
                int side = (int)(h * 0.80);
                int top = minY + (int)(h * 0.05);
                int cx = (minX + maxX) / 2;
                int left = cx - side / 2;
                if (left < 0) left = 0;
                if (top + side > cell) top = cell - side;
                if (top < 0) top = 0;
                if (left + side > cell) left = cell - side;
                if (side <= 0) return;

                var head = new CroppedBitmap(conv, new Int32Rect(left, top, side, side));
                head.Freeze();

                Avatar.Fill = new ImageBrush(head) { Stretch = Stretch.UniformToFill };
                if (AvatarText != null) AvatarText.Visibility = Visibility.Collapsed;
            }
            catch
            {
                // 头像加载失败不影响聊天
            }
        }

        /// <summary>把窗口放在桌宠正上方；放不下就放下方</summary>
        public void PositionNear(Window owner)
        {
            if (owner == null) return;

            double myH = ActualHeight > 0 ? ActualHeight : 190;   // SizeToContent 下 Height 是 NaN
            double areaRight = SystemParameters.WorkArea.Right;
            double x = owner.Left + (owner.ActualWidth - Width) / 2.0;
            double y = owner.Top - myH + 10;   // 尾巴尖大致落在桌宠头顶

            if (y < SystemParameters.WorkArea.Top)
            {
                y = owner.Top + owner.ActualHeight - 10;
            }
            if (x < SystemParameters.WorkArea.Left) x = SystemParameters.WorkArea.Left;
            if (x + Width > areaRight) x = areaRight - Width;

            Left = x;
            Top = y;
            _anchorBottom = y + myH;      // 记住底边，之后高度变化都以此为准

            _lastOwnerLeft = owner.Left;
            _lastOwnerTop = owner.Top;
            StartFollow();

            // 布局完成后再校准一次真实高度
            Dispatcher.BeginInvoke(new Action(delegate
            {
                if (ActualHeight > 0) _anchorBottom = Top + ActualHeight;
            }));
        }

        // ---------- 跟随桌宠 ----------

        private void StartFollow()
        {
            if (_followTimer == null)
            {
                _followTimer = new DispatcherTimer();
                _followTimer.Interval = TimeSpan.FromMilliseconds(70);
                _followTimer.Tick += Follow_Tick;
            }
            _followTimer.Start();
        }

        /// <summary>按桌宠位移的增量同步自身位置，保留用户手动调整过的相对偏移</summary>
        private void Follow_Tick(object sender, EventArgs e)
        {
            Window o = Owner;
            if (o == null || !IsVisible) return;

            double ol = o.Left, ot = o.Top;
            if (double.IsNaN(_lastOwnerLeft))
            {
                _lastOwnerLeft = ol;
                _lastOwnerTop = ot;
                return;
            }

            double dx = ol - _lastOwnerLeft;
            double dy = ot - _lastOwnerTop;
            if (Math.Abs(dx) < 0.5 && Math.Abs(dy) < 0.5) return;

            Left += dx;
            Top += dy;
            _lastOwnerLeft = ol;
            _lastOwnerTop = ot;
            ClampToScreen();
            _anchorBottom = Top + ActualHeight;   // 跟着角色移动后更新锚点
        }

        private void ClampToScreen()
        {
            Rect wa = SystemParameters.WorkArea;
            if (Left < wa.Left) Left = wa.Left;
            if (Top < wa.Top) Top = wa.Top;
            if (Left + Width > wa.Right) Left = wa.Right - Width;
            if (Top + Height > wa.Bottom) Top = wa.Bottom - Height;
        }

        private void HideChat()
        {
            if (_followTimer != null) _followTimer.Stop();
            StopSpeaking();
            Hide();
        }

        // ---------- 展开 / 折叠 ----------

        private const double ExpandedHeight = 440;
        private const double CollapsedMessageMax = 300;   // 折叠时消息区上限，超了滚动
        private bool _expanded;
        private double _anchorBottom = double.NaN;

        private void ToggleArea_MouseDown(object sender, MouseButtonEventArgs e)
        {
            e.Handled = true;   // 防止触发头部拖动
        }

        private void Expand_Click(object sender, MouseButtonEventArgs e)
        {
            ToggleExpanded();
        }

        private void ToggleExpanded()
        {
            _expanded = !_expanded;

            if (_expanded)
            {
                SizeToContent = SizeToContent.Manual;
                Height = ExpandedHeight;
            }
            else
            {
                // 折叠时高度交给内容决定，短回复窗口就矮，长回复也不会被截
                SizeToContent = SizeToContent.Height;
            }

            if (ExpandIcon != null) ExpandIcon.Text = _expanded ? "▼" : "▲";
            RefreshVisibility();
            Input.Focus();
        }

        /// <summary>尺寸变化后保持底部不动（尾巴始终指向桌宠）</summary>
        private void Window_SizeChanged(object sender, SizeChangedEventArgs e)
        {
            if (double.IsNaN(_anchorBottom) || ActualHeight <= 0) return;

            double want = _anchorBottom - ActualHeight;
            if (Math.Abs(Top - want) > 0.5)
            {
                Top = want;
                ClampToScreen();
            }
        }

        /// <summary>
        /// 折叠时只留最后一条回复；展开时全部显示。
        /// 还没有回复（只有提问）就显示最后一条，免得界面空着。
        /// </summary>
        private void RefreshVisibility()
        {
            if (MsgPanel == null) return;

            int count = MsgPanel.Children.Count;
            if (count == 0) return;

            int lastAssistant = -1;
            for (int i = 0; i < count; i++)
            {
                var b = MsgPanel.Children[i] as Border;
                if (b != null && "assistant".Equals(b.Tag)) lastAssistant = i;
            }
            if (lastAssistant < 0) lastAssistant = count - 1;

            for (int i = 0; i < count; i++)
            {
                var el = MsgPanel.Children[i] as UIElement;
                if (el == null) continue;
                el.Visibility = (_expanded || i == lastAssistant) ? Visibility.Visible : Visibility.Collapsed;
            }

            if (Scroller != null)
            {
                Scroller.VerticalScrollBarVisibility = _expanded
                    ? ScrollBarVisibility.Auto
                    : ScrollBarVisibility.Hidden;
                Scroller.MaxHeight = _expanded
                    ? double.PositiveInfinity
                    : CollapsedMessageMax;
            }
            if (_expanded) Scroller.ScrollToEnd();
        }

        // ---------- 窗口拖动 ----------

        private void Header_MouseDown(object sender, MouseButtonEventArgs e)
        {
            try { DragMove(); } catch { }
        }

        private void Window_KeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Escape) HideChat();
        }

        // ---------- 气泡 ----------

        private TextBlock AddBubble(string text, bool isUser)
        {
            var tb = new TextBlock
            {
                Text = text,
                TextWrapping = TextWrapping.Wrap,
                FontSize = 13,
                FontFamily = new FontFamily("Microsoft YaHei UI"),
                LineHeight = 20
            };

            var bubble = new Border
            {
                Child = tb,
                MaxWidth = 230,
                Padding = new Thickness(11, 8, 11, 8),
                Margin = new Thickness(0, 0, 0, 9),
                HorizontalAlignment = isUser ? HorizontalAlignment.Right : HorizontalAlignment.Left,
                CornerRadius = isUser ? new CornerRadius(14, 14, 4, 14) : new CornerRadius(14, 14, 14, 4),
                Tag = isUser ? "user" : "assistant"
            };

            if (isUser)
            {
                bubble.Background = UserBg;
                tb.Foreground = UserText;
            }
            else
            {
                bubble.Background = AssistantBg;
                bubble.BorderBrush = AssistantBorder;
                bubble.BorderThickness = new Thickness(1);
                tb.Foreground = AssistantText;
            }

            MsgPanel.Children.Add(bubble);
            Scroller.ScrollToEnd();
            return tb;
        }

        // ---------- 输入 ----------

        private void Input_TextChanged(object sender, TextChangedEventArgs e)
        {
            if (Placeholder != null)
            {
                Placeholder.Visibility = string.IsNullOrEmpty(Input.Text)
                    ? Visibility.Visible : Visibility.Collapsed;
            }
        }

        private void Input_KeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Enter)
            {
                e.Handled = true;
                Send();
            }
        }

        private void Send_Click(object sender, MouseButtonEventArgs e)
        {
            Send();
        }

        private void Close_MouseDown(object sender, MouseButtonEventArgs e)
        {
            e.Handled = true;   // 防止触发头部拖动
        }

        private void Close_Click(object sender, MouseButtonEventArgs e)
        {
            HideChat();
        }

        private void Send()
        {
            if (_busy) return;
            string q = (Input.Text ?? "").Trim();
            if (q.Length == 0) return;

            Input.Text = "";
            _busy = true;
            _pending.Length = 0;

            AddBubble(q, true);
            _streamTarget = AddBubble("…", false);
            RefreshVisibility();

            var msgs = new List<Dictionary<string, object>>();
            msgs.Add(MakeMsg("system",
                _persona + "\n（今天是 " + DateTime.Now.ToString("yyyy-MM-dd dddd") + "）"));

            int start = Math.Max(0, _history.Count - OllamaClient.HistoryRounds * 2);
            for (int i = start; i < _history.Count; i++) msgs.Add(_history[i]);
            msgs.Add(MakeMsg("user", q));

            OllamaClient.ChatStream(
                msgs,
                delegate (string piece)
                {
                    _pending.Append(piece);
                    Dispatcher.BeginInvoke(new Action(delegate
                    {
                        if (_streamTarget != null) _streamTarget.Text = _pending.ToString();
                        Scroller.ScrollToEnd();
                    }));
                },
                delegate
                {
                    string full = _pending.ToString();
                    string display, japanese;
                    ParseReply(full, out display, out japanese);

                    _history.Add(MakeMsg("user", q));
                    _history.Add(MakeMsg("assistant", full));
                    _busy = false;

                    TextBlock target = _streamTarget;
                    _streamTarget = null;

                    Dispatcher.BeginInvoke(new Action(delegate
                    {
                        if (target != null) target.Text = display;
                        Scroller.ScrollToEnd();
                        Speak(japanese);
                    }));
                },
                delegate (string err)
                {
                    _busy = false;
                    Dispatcher.BeginInvoke(new Action(delegate
                    {
                        if (_streamTarget != null) _streamTarget.Text = "[出错] " + err;
                        _streamTarget = null;
                        Scroller.ScrollToEnd();
                    }));
                });
        }

        // ---------- 朗读（本地 VITS 服务）----------

        /// <summary>
        /// 把日语文本发给本地 TTS 服务，拿回 wav 播放。
        /// 服务没起就静默跳过，不影响对话。
        /// </summary>
        private void Speak(string japanese)
        {
            if (!Settings.TtsEnabled) return;
            string clean = (japanese ?? "").Trim();
            if (clean.Length == 0) return;

            string payload = "{\"text\":" + JsonEscape(clean) +
                             ",\"speed\":" + TtsSpeed.ToString("0.##", CultureInfo.InvariantCulture) + "}";

            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    byte[] body = Encoding.UTF8.GetBytes(payload);
                    var req = (HttpWebRequest)WebRequest.Create(TtsUrl + "/tts");
                    req.Method = "POST";
                    req.ContentType = "application/json; charset=utf-8";
                    req.Proxy = null;              // 绕过系统代理
                    req.Timeout = 60000;
                    req.ReadWriteTimeout = 60000;
                    using (Stream s = req.GetRequestStream()) s.Write(body, 0, body.Length);

                    byte[] wav;
                    using (var resp = (HttpWebResponse)req.GetResponse())
                    using (var ms = new MemoryStream())
                    {
                        using (Stream rs = resp.GetResponseStream()) rs.CopyTo(ms);
                        wav = ms.ToArray();
                    }

                    Dispatcher.BeginInvoke(new Action(delegate { PlayWav(wav); }));
                }
                catch
                {
                    // TTS 服务未启动时静默跳过
                }
            });
        }

        private void PlayWav(byte[] wav)
        {
            try
            {
                if (_player != null)
                {
                    try { _player.Stop(); } catch { }
                    _player.Dispose();
                    _player = null;
                }

                _playerStream = new MemoryStream(wav);
                _player = new SoundPlayer(_playerStream);
                _player.Play();      // 异步播放
            }
            catch
            {
            }
        }

        /// <summary>
        /// 拆出「中文显示 / 日语朗读」两段。
        /// 模型没按格式输出时，中文段退回全文，日语段为空（不朗读，免得念出乱码）。
        /// </summary>
        private static void ParseReply(string full, out string display, out string japanese)
        {
            display = (full ?? "").Trim();
            japanese = null;

            Match jp = Regex.Match(full ?? "", @"\[日\]\s*([^\r\n]+)");
            if (jp.Success) japanese = jp.Groups[1].Value.Trim();

            Match zh = Regex.Match(full ?? "", @"\[中\]\s*([^\r\n]+)");
            if (zh.Success) display = zh.Groups[1].Value.Trim();
            else if (jp.Success) display = Regex.Replace(full, @"\[[中日本]\]", "").Trim();

            if (display.Length == 0) display = (full ?? "").Trim();
        }

        private static string JsonEscape(string s)
        {
            var sb = new StringBuilder(s.Length + 8);
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
            return sb.ToString();
        }

        private void StopSpeaking()
        {
            try
            {
                if (_player != null)
                {
                    _player.Stop();
                    _player.Dispose();
                    _player = null;
                }
            }
            catch { }
        }

        /// <summary>去掉 markdown 标记和符号，避免念出「星号星号」</summary>
        private static string StripForSpeech(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = Regex.Replace(s, @"```[\s\S]*?```", " ");
            s = Regex.Replace(s, @"`([^`]*)`", "$1");
            s = Regex.Replace(s, @"\$\$?([^$]*)\$\$?", "$1");
            s = Regex.Replace(s, @"^[ \t]*[-*+][ \t]+", "", RegexOptions.Multiline);
            s = Regex.Replace(s, @"^[ \t]*#{1,6}[ \t]*", "", RegexOptions.Multiline);
            s = Regex.Replace(s, @"[*_#>~\[\]]", "");
            s = Regex.Replace(s, @"\s+", " ");
            return s.Trim();
        }

        private static Dictionary<string, object> MakeMsg(string role, string content)
        {
            var d = new Dictionary<string, object>();
            d["role"] = role;
            d["content"] = content;
            return d;
        }
    }
}
