// 掼蛋人机对战 —— 原生窗口外壳（WebView2）
//
// 为什么不用浏览器：Edge 的 --app 模式在「以管理员权限运行」的机器上会被拒绝，
// 窗口一片空白。WebView2 是进程内嵌的浏览器控件，不受这个限制。
//
// 编译（见 tools/build_window_host.py）：
//   csc /nologo /target:winexe /platform:x64 /out:GuandanWindow.exe
//       /r:Microsoft.Web.WebView2.Core.dll /r:Microsoft.Web.WebView2.WinForms.dll
//       GuandanWindow.cs
//
// 用法：GuandanWindow.exe <url> [用户数据目录] [调试端口]

using System;
using System.Drawing;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace GuandanHost
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            string url = args.Length > 0 ? args[0] : "http://127.0.0.1:8765/";
            string dataDir = args.Length > 1 ? args[1] : null;
            string debugPort = args.Length > 2 ? args[2] : null;
            string browserArgs = null;
            if (!string.IsNullOrEmpty(debugPort) && debugPort != "0")
            {
                browserArgs = "--remote-debugging-port=" + debugPort;
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            var form = new Form
            {
                Text = "掼蛋人机对战 v1.1",
                Width = 1280,
                Height = 900,
                MinimumSize = new Size(960, 700),
                StartPosition = FormStartPosition.CenterScreen,
                BackColor = Color.FromArgb(10, 61, 44),
            };

            var web = new WebView2 { Dock = DockStyle.Fill };
            form.Controls.Add(web);

            form.Shown += async (sender, e) =>
            {
                try
                {
                    CoreWebView2EnvironmentOptions options = null;
                    if (!string.IsNullOrEmpty(browserArgs))
                    {
                        options = new CoreWebView2EnvironmentOptions(browserArgs);
                    }
                    var environment = await CoreWebView2Environment.CreateAsync(null, dataDir, options);
                    await web.EnsureCoreWebView2Async(environment);
                    var settings = web.CoreWebView2.Settings;
                    settings.AreDefaultContextMenusEnabled = false;
                    settings.IsStatusBarEnabled = false;
                    settings.AreDevToolsEnabled = false;
                    web.CoreWebView2.Navigate(url);
                }
                catch (Exception error)
                {
                    MessageBox.Show(
                        "窗口初始化失败：" + error.Message + "\n\n可以把控制台里的地址复制到浏览器里玩。",
                        "掼蛋人机对战",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Warning);
                    form.Close();
                }
            };

            Application.Run(form);
        }
    }
}
