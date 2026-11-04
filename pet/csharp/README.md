# C# 集成文件（覆盖式补丁）

把下面四个文件复制到上游 `Desktop_Gremlin/` 源码目录（与 `MainWindow.xaml.cs` 同级）：

| 文件 | 类型 | 说明 |
|---|---|---|
| `OllamaClient.cs` | 新增 | 最小 Ollama 客户端，流式 SSE 解析，`req.Proxy = null` 绕过系统代理 |
| `TtsLauncher.cs` | 新增 | TTS 服务管家：探测端口、拉起进程、`taskkill /T` 连树清理 |
| `ChatWindow.xaml` | 新增 | 气泡窗口布局，折叠 190 / 展开 440 |
| `ChatWindow.xaml.cs` | 新增 | 历史管理、双语解析、跟随定位、头像裁切、朗读 |

覆盖后**还需要手动改三处**（上游文件不能直接覆盖，否则丢上游逻辑）：

1. `Desktop_Gremlin.csproj` — 加 3 个 `Compile` + 1 个 `Page` 条目
2. `MainWindow.xaml(.cs)` — `SpriteImage` 绑定 `MouseRightButtonDown` + 处理函数
3. `App.xaml.cs` / `ConfigManager.cs` / `SpriteVariables.cs` — 退出清理 + 四个 `TTS_*` 配置项

完整步骤和代码片段见 [`docs/03-桌宠集成.md`](../../docs/03-桌宠集成.md)。

---

编译前记得删掉 csproj 里指向缺失素材的 `<Content Include="SpriteSheet\...">` 条目（那些 PNG 只在 release zip 里，编译不需要）。

上游版本：`v4.0` (`0a7bd2c`)。换版本后这些文件可能需要重新对齐——尤其 `ChatWindow.xaml.cs` 里对 `Settings` / `GremlinState` 的引用。
