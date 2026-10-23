# 发票整理

本项目以非破坏方式整理中国发票和报销票据。原始文件始终保留在 `input/`，内部计划位于 `.runtime/`，最终结果位于 `output/`。

## 本地网页

安装依赖并启动：

```powershell
python -m pip install -r requirements.txt
python run.py
```

浏览器访问 `http://127.0.0.1:8000`，上传 PDF 或 ZIP，识别预览后确认整理，即可下载 `发票整理结果.zip`。

网页版是本地单用户应用。网页上传副本、输出和运行文件统一放在数据根目录的 `.runtime/web-batch/` 内，与 CLI 的 `input/`、`output/` 及共享 `.runtime/` 中的回归记录、发布报告隔离。

新网页批次仅清理专属 `input/` 的 PDF/ZIP、`output/` 的 PDF/XLSX，以及专属运行目录内固定的计划、预览和结果 ZIP，不递归删除子目录或清空共享 `.runtime/`。旧版留在项目根目录的数据保持原样。临时文件被占用或无权清理时，页面提示关闭文件、检查权限后重试；不会再次清理来覆盖原始错误。

支持旧式增值税电子普通发票、文字分层的电子普通／专用发票，以及地铁、城际铁路、机场巴士和用车的配套行程单。以票面结构判断文档角色，优先使用实际出行日期及入住日期排序。票面服务类型与原文件名声明的报销用途分别保留，文件名不覆盖真实金额、税额或票号。

行程单仅在能可靠且唯一对应发票时共享序号。同额多候选、正文证据冲突或字段不足时，列为整理失败，显示已识别字段，原名原字节保留；不会强行配对或标为纸质票。已确认缺对应电子发票的市内交通行程单正常命名、独立排序，并添加“（对应纸质发票）”。物流收款凭证单独标为辅助凭证，凭证号不当作发票号码。纯图像 PDF 不进行 OCR，不擅自拆分多页 PDF。

无法匹配任何命名规则的 PDF 在识别预览中显示原文件名及 `[无有效发票号码]`，并在表格外单独列出；已识别的行程单仍优先按行程单规则命名，发票号码留空。确认后显示整理成功、失败的 PDF 张数及失败文件列表。下载 ZIP 包含所有输入 PDF：无法整理的文件保留原始内容和文件名；发生同名冲突时，仅在 ZIP 内用子目录区分，不覆盖文件。

同名输入逐份保留独立来源身份，不静默跳过。仅在完整导入的 PDF 全部通过数量与字节校验后报告交付成功；规则整理失败与文件交付失败分别提示。无法完整读取的 ZIP 会明确报错，不将部分读取结果报告为完整成功。

Excel 保持原有 12 列，逐行“票面总金额”仍展示每份文档自身金额；末行“合计”按独立费用计算，发票与配套行程只计一次，确认对应纸质票的独立行程计一次，辅助凭证与待复核文件不计入。金额列批注和各行备注说明这一口径，因此末行可能小于所有文档金额直接相加。

## Windows 桌面模式

v1.1.10 采用“留白·微紫”界面：黑白与低饱和微紫配色，顶部显示处理进度，主要操作统一位于页面右上方。上传页采用文件清单与拖放区分栏，预览页保留完整六列，完成页集中展示整理结果和下载入口。发票识别、分类、排序、金额计算及文件保留规则均保持不变。

源码环境可直接启动独立窗口：

```powershell
python desktop.py
```

桌面入口在后台线程启动仅监听 `127.0.0.1:8000` 的 FastAPI 服务，并使用 pywebview 的 Edge WebView2 窗口加载现有页面。关闭主窗口时会通知 uvicorn 正常退出并等待后台线程结束。

发布版运行数据位于：

```text
%LOCALAPPDATA%\InvoiceOrganizer\
└── .runtime\
    └── web-batch\
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

## 版本发布

正式版本号统一读取根目录的 `VERSION`。完整构建与归档命令为：

v1.1.00 的产品、安装包和 Release 保留该显示格式；为兼容旧客户端，自动更新协议使用数值等价的 `1.1.0`。两者按数字段比较相等，不会重复提示更新，旧版用户仍可取得完整安装包升级。

```powershell
.\build-release.ps1
```

本地归档、GitHub Release 和自建更新服务器使用不同的固定命名规则。详细发布步骤见 [RELEASE.md](RELEASE.md)。`build-release.ps1` 会根据 `VERSION` 生成本地中文归档，并在独立的 `..\dist\publish\vX.X.X\` 中生成 GitHub 与更新服务器可直接使用的英文副本，同时打印中文显示说明。

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
