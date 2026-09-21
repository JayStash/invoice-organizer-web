# 发票整理

本项目以非破坏方式整理中国发票和报销票据。原始文件始终保留在 `input/`，内部计划位于 `.runtime/`，最终结果位于 `output/`。

## 本地网页

安装依赖并启动：

```powershell
python -m pip install -r requirements.txt
python run.py
```

浏览器访问 `http://127.0.0.1:8000`，上传 PDF 或 ZIP，识别预览后确认整理，即可下载 `发票整理结果.zip`。

网页版是本地单用户应用。开始新的网页批次时，会清理项目内上一批的 `input/`、`output/` 和 `.runtime/` 数据。

## Windows 桌面模式

源码环境可直接启动独立窗口：

```powershell
python desktop.py
```

桌面入口在后台线程启动仅监听 `127.0.0.1:8000` 的 FastAPI 服务，并使用 pywebview 的 Edge WebView2 窗口加载现有页面。关闭主窗口时会通知 uvicorn 正常退出并等待后台线程结束。

发布版运行数据位于：

```text
%LOCALAPPDATA%\InvoiceOrganizer\
├── input\
├── output\
└── .runtime\
```

准备好依赖后可在 `invoice-organizer-web` 目录运行 `build.ps1` 生成 onedir 发布目录。最终成品统一输出到项目根目录：

```text
..\dist\发票整理工具\
```

本项目的 `invoice-organizer.spec` 使用 `console=False` 隐藏发布版控制台，并显式打包 `app/templates`、`app/static` 与 pywebview 资源。

## Windows 安装包

安装 Inno Setup 6 后，在 `invoice-organizer-web` 目录运行：

```powershell
.\build-installer.ps1
```

脚本使用项目根目录下的 `..\dist\发票整理工具\` 作为安装源，并输出：

```text
..\dist\installer\发票整理工具-Setup.exe
```

## CLI 使用

1. 把需要整理的原始票据放入 `input/`。
2. 只读扫描：

   ```powershell
   python scripts/scan_invoices.py
   ```

3. 查看 `.runtime/发票整理预览.md`，核对命名、顺序、字段和待确认项。
4. 明确确认后，使用预览中的令牌执行：

   ```powershell
   python scripts/organize_invoices.py --plan .runtime/.invoice-organization-plan.json --confirm <TOKEN>
   ```

5. 校验并查看结果：

   ```powershell
   python scripts/validate_organization.py --plan .runtime/.invoice-organization-plan.json
   ```

`output/` 只包含整理后的票据文件和 `发票整理清单.xlsx`。ZIP 只读处理并永久保留在 input；ZIP 中非 PDF 成员不会输出。

## 自定义目录

```powershell
python scripts/scan_invoices.py --input "D:\报销资料\input" --output "D:\报销资料\output"
```

`.runtime` 始终位于 Skill 项目根目录。input 与 output 不能相同或互相嵌套。

## 依赖

```powershell
python -m pip install -r requirements.txt
```
