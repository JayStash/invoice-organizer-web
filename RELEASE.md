# 发票整理工具正式版本发布规范

本文件是 Codex 执行本项目版本发布与收尾的权威流程依据。README 的发布入口指向本文件；旧对话、历史服务器配置或零散命令不能覆盖这里的当前配置。用户本次明确指令优先；如果指令与 VERSION、服务器配置或实际产物矛盾，报告并停止，不自行猜测。

## 1. 触发、范围与安全边界

- 用户明确说“开发完成，收尾发布”或等价指令后，Codex 必须先完整阅读本文件，再自动执行第一阶段“发布前预检”。必检项全部 PASS 后自动进入第二阶段“正式发布”，不再等人工确认；任一项 BLOCKED 则立即停止并报告，不得自行绕过。
- “只检查”“只更新文档”“先测试”“暂不发布”不构成正式发布授权。
- 发布不包含修改发票业务逻辑、UI、代理规则、稳定 Skill 或用户运行数据。不得为通过发布检查而修改无关功能。
- Windows 命令统一使用 PowerShell 7（pwsh），第一条 shell 操作确认 $PSVersionTable.PSVersion.Major 为 7。
- 不把密码、Token、SSH 私钥或其他凭据写入代码、本文件、日志、commit 或 GitHub Release；使用现有 Git/gh/SSH 凭据配置。
- 不提交真实发票、运行数据或构建缓存；不删除、覆盖历史版本，不强推，不移动已存在的正式 tag，不丢弃工作区修改。
- 桌面 EXE 启动验证受环境策略限制时，记录“skipped：环境策略限制”，不绕过限制、不因此阻塞发布；用户明确要求跳过时也记录原因。其他测试和产物校验仍须通过。

## 2. 当前项目与统一版本来源

| 项目 | 当前值 |
| --- | --- |
| 工作目录 | D:\AI项目\智能发票整理\invoice-organizer-web |
| 统一成品目录 | D:\AI项目\智能发票整理\dist，即源码目录的 ..\dist |
| 版本来源 | Web 项目根目录 VERSION |
| Git 分支 | master |
| Git remote | origin：https://github.com/JayStash/invoice-organizer-web.git |
| GitHub 仓库 | JayStash/invoice-organizer-web |
| 构建入口 | build-release.ps1 |
| Windows 应用 | PyInstaller onedir，invoice-organizer.spec |
| 安装程序 | Inno Setup，installer\invoice-organizer.iss |
| 当前发行类型 | Setup 和完整 Portable ZIP，两者均为必需产物 |

VERSION 只允许规范的三个数字段，例如 1.0.30，不带 v；tag/Release 使用 v1.0.30。1.0.3、1.0.30、1.030 不可互换，不能擅自纠正用户指定版本。

版本按数字段比较，例如 (1, 0, 30) > (1, 0, 22)，禁止字符串直接比较。普通正式发布必须高于当前公网正式版本；部分发布的同版本只允许校验后续跑。版本倒退或同版本不同内容属于冲突，停止。

特别注意：1.0.3 < 1.0.22 < 1.0.30，不按小数比较，也不能把 1.0.3 当作 1.0.30 的简写。若用户指定低于已发布版本的号码，可按要求修改开发源码中的 VERSION，但必须在构建、commit/tag、上传或切换 latest.json 前报告冲突并暂停。不能擅自修改客户端比较规则、伪造版本顺序或将较低版本标为最新；应由用户重新确定高于公网版本的正式版本号。

PyInstaller spec、Inno Setup 和客户端均已从 VERSION 读取版本。不得多处另行维护版本常量，不得仅改名旧安装包冒充新版本。

### 目录与命名

以下路径均相对统一 dist，而不是 Web 源码内部的 dist：

| 用途 | 路径 |
| --- | --- |
| 本次 onedir 构建 | 发票整理工具\，包含 EXE、_internal 等全部文件 |
| 本次 Setup 构建 | installer\发票整理工具-Setup.exe |
| 中文便携版归档 | releases\vX.X.X\发票整理工具-Windows-x64-vX.X.X.zip |
| 中文安装版归档 | releases\vX.X.X\发票整理工具-Setup-vX.X.X.exe |
| 英文便携版上传副本 | publish\vX.X.X\invoice-organizer-Windows-x64-vX.X.X.zip |
| 英文安装版上传副本 | publish\vX.X.X\invoice-organizer-Setup-vX.X.X.exe |
| 本次发布元数据 | publish\vX.X.X\latest.json |

本地归档保持中文，不为上传改名；GitHub asset 和服务器 Setup 使用英文副本。GitHub asset label 分别为“发票整理工具 vX.X.X 便携版”和“发票整理工具 vX.X.X 安装版”。

build-release.ps1 集中管理命名，依次调用 build.ps1、build-installer.ps1，归档并复制英文产物。它目前只负责本地构建与归档，不生成 latest.json，不执行 Git/GitHub/服务器发布；其余步骤由 Codex 按本文件完成。脚本拒绝覆盖已存在的版本归档/上传副本，不得删除旧成品绕过此保护。

## 3. 当前正式更新服务器

| 项目 | 正式值 |
| --- | --- |
| SSH alias | invoice-server |
| 服务器 IP | 47.250.145.239 |
| 系统 / 用户 | Ubuntu / root |
| 更新域名 | https://update.jaystash.online |
| 服务器磁盘根目录 | /var/www/invoice-organizer |
| 安装包目录 | /var/www/invoice-organizer/releases |
| 临时上传目录 | /var/www/invoice-organizer/tmp |
| 正式元数据文件 | /var/www/invoice-organizer/latest.json |
| 公网元数据地址 | https://update.jaystash.online/invoice-organizer/latest.json |
| 公网安装包地址 | https://update.jaystash.online/invoice-organizer/releases/invoice-organizer-Setup-vX.X.X.exe |

公网 URL 的 /invoice-organizer/releases/ 不是服务器磁盘目录；磁盘路径必须包含 /var/www。

使用 ssh invoice-server 和 scp ... invoice-server:... 操作。连接前用 ssh -G invoice-server 核对最终 hostname/user，必须与本表一致；核对域名 DNS 指向当前服务器。使用严格 SSH 主机密钥校验，主机密钥不匹配时停止，不关闭校验或自动接受冲突密钥。

废弃服务器 120.79.151.217 仅在本段作为禁止连接说明出现，不能用于 SSH、HTTP、download_url、客户端允许主机或回退地址。服务器/SSH alias 迁移时，必须由用户明确提供新信息，先更新本文件，再继续发布；不因连接失败自行换服务器。

app/update_client.py 的 UPDATE_METADATA_URL、ALLOWED_UPDATE_HOST、测试地址和发布示例必须与正式域名一致。不得修改代理规则绕过失败。发布通常不修改 Nginx；如确认为配置问题，停止报告原因和必要变更，依用户明确授权处理。

## 4. 第一阶段：发布前预检（强制门禁）

每次收尾或中断续跑都先执行本节。不得直接从 commit、tag、GitHub Release 或服务器上传开始，不得仅依据上次对话声称“预检已通过”。以下检查按顺序执行；发现 BLOCKED 时立即停止后续检查和正式发布，未执行项如实标记 NOT_RUN。

### 4.1 状态、权限与自动衔接

- PASS：检查实际成功，具备可核对的证据；文件存在、TCP 22 可达、HTTPS 可达均不能替代实际 SSH 登录成功。
- BLOCKED：必检项失败、超时、凭据无效、版本/哈希冲突、产物缺失或无法验证等。立即停止、报告，不将失败降为警告后继续，不自行切换服务器/代理/认证或关闭安全校验。
- NOT_RUN：被前置阻塞挡住的检查，不算 PASS。
- SKIPPED：仅允许桌面 EXE 启动验证因环境策略限制或用户明确要求跳过，记录原因，不阻塞其余必检项。不得将 SSH、scp、测试、SHA256、JSON 或公网校验标为 SKIPPED。
- 预检不 commit、不创建 tag、不 push、不创建或修改 GitHub Release、不上传正式 Setup/ZIP、不修改正式 latest.json、Nginx、业务代码、UI、代理或 SSH 配置，不启动桌面 EXE。不得通过实际发布操作来“验证发布权限”。
- 唯一允许的远端写入是无敏感信息的临时 scp 测试文件：在已存在的 tmp 目录创建唯一文件，核对哈希，完成后删除该文件并确认删除成功。不清理其他文件，不改正式目录内容。本地测试及报告放入隔离临时目录或已忽略的 .runtime，不触碰用户输入、输出和 LocalAppData 数据。
- 有效发布文件应在开发/构建准备阶段生成。预检只校验，不为已有文件重复构建；若缺失或失效，标为 BLOCKED 并说明需补齐/构建，不能以“第二阶段再构建”为由标 PASS。用户完成或明确要求补齐后，重新从本阶段检查。
- 所有必检项 PASS 后，汇总预检结果并自动继续第 5 节，不再请求人工确认。用户仅授权“预检”时则汇总后停止，绝不自动发布。
- 源码、VERSION、产物、目标服务器或凭据状态发生变化，之前的相关 PASS 失效，须重新检查；仅本发布文档等非打包资料修改且确认不影响程序内容时，不要求无意义重建。失败处理后，由用户要求继续时重新预检，不在 BLOCKED 状态自行重试发布。

### 4.2 按顺序执行的预检清单

**P00：本地执行上下文及服务器身份**

确认 PowerShell 7、Web 项目路径、用户目标版本。先读取 ssh -G invoice-server 的最终 hostname/user/port，必须为 47.250.145.239 / root / 22；解析 update.jaystash.online，确认指向当前正式服务器。身份不一致即 BLOCKED，未确认前不连接。alias/服务器变化须按第 3 节先更新本文件，不能绕过 alias 另连其他主机。

**P01：新服务器 SSH 与临时上传**

通过 ssh invoice-server 实际登录，启用严格主机密钥校验及有限连接/存活超时，执行 whoami、hostname，并检查：

- 用户确为 root，远程命令正常返回。
- /var/www/invoice-organizer、releases、tmp 存在；releases、tmp、根目录以及已有 latest.json 具备所需读写权限。
- python3、sha256sum、stat、同目录原子重命名所需命令可用。
- 只读记录当前 latest.json、历史安装包和本次目标路径；同版本正式文件或临时文件已存在时检查归属/哈希，未知来源或冲突则 BLOCKED。
- 通过 scp 上传唯一临时测试文件到 tmp，实际远端计算 SHA256 与本地对照，再删除并确认不存在。测试失败后的已知临时文件也只做必要清理；清理失败必须报告路径，不能声称已清理。

SSH 超时、密钥或认证失败立即 BLOCKED；TCP 端口连通、网页可访问不代表此项成功。预检不会改 sshd、防火墙、安全组或 Nginx。

**P02：当前正式更新服务**

读取正式 HTTPS latest.json，要求 HTTP 200、JSON 可解析，记录当前 version、download_url、sha256。URL 必须使用 update.jaystash.online，不含废弃 IP，不回退 HTTP 或第三方主机。读取当前正式 Setup（不是尚未发布的目标版本），验证 HTTP 200、Content-Length 为正确字节数、完整下载 SHA256 与 JSON 及服务器文件一致。

历史 JSON 缺少 changelog 不单独判为服务故障，但必须记录，并按第 7 节从可靠历史记录确认可补齐；无法恢复历史说明则 BLOCKED。本次版本必须数字递增，同版本仅允许已核验的中断续跑。

**P03：本地 VERSION 与发布产物**

检查 VERSION 等于用户目标；EXE 文件版本、打包内 _internal\VERSION、Setup 版本与归档/上传文件名均一致。检查本版中文归档和英文上传副本均存在、非空，记录 Setup/Portable ZIP 的绝对路径、字节数、SHA256，确认同类副本字节一致。当前项目提供 Portable ZIP，因此不能因遗漏 ZIP 而跳过。

检查 ZIP 完整性及完整 onedir 结构，不能只有 EXE；不含真实发票、input/output 用户数据、.runtime、.git、tests 或开发缓存。核对构建日志、打包资源及构建后源码变化，确认产物来自当前拟提交源码，不能只凭文件名复用旧构建。缺失或来源无法确认则 BLOCKED。

**P04：Git 状态及修改归属**

检查当前 branch、remote、git status、git diff、git diff --cached、未跟踪文件、本地及远端 vX.X.X tag。应为 master 和第 2 节的 origin；审阅所有变更，确认仅含本版源码、文档、资源和脱敏测试，不含真实发票或凭据。不盲目 git add .，不通过 stash/reset/restore 丢弃用户改动。待发布的本版未提交修改是正常状态，不要求预检时 clean；无关变更无法安全归属、tag 指向冲突等才 BLOCKED。已有本版提交/tag 记录其状态供第二阶段复用，预检中不创建或推送。

**P05：GitHub 身份、仓库和 Release**

检查 gh auth status，访问 JayStash/invoice-organizer-web，确认有推送和 Release 管理权限，核对 GitHub remote、远端 tag、vX.X.X Release 的存在性、draft/prerelease 状态、目标 tag 和附件清单。已有同名附件核对大小/hash；一致可留待续跑，不一致 BLOCKED。认证失败、无法访问或权限不足不能跳过。本项只读，不创建/编辑 Release，不上传、不 push。

**P06：回归、更新地址及元数据准备**

运行 python -m unittest discover -s tests -v，记录通过数量。涉及发票规则时，需当前源码的真实失败样本回归及现有正常样本兼容性结果，使用隔离目录，原件哈希不变，只提交脱敏 fixture。此前同一程序源码已通过的真实样本结果可在确认来源与源码未变后复用，不能复用其他版本结果。

检查 app/update_client.py、tests/test_update_client.py、RELEASE.md、VERSION：运行配置、测试地址和发布示例均使用当前正式域名；旧 IP 只允许出现在明确的禁止连接说明中。确认本次发布说明、历史 changelog 的来源与合并方案，满足第 7 节。桌面 EXE 启动验证不执行，记 SKIPPED 并注明策略限制或本次授权边界。

**P07：发布链路能力与门禁结论**

确认 Git 作者/提交者身份有效、无仓库锁，具备 commit/tag 的本地条件；根据认证、仓库权限和远端可达性确认 push、创建 Release、上传 Setup/ZIP 的条件；根据 P01 确认 SSH/scp、远端写入、SHA256、JSON 校验与 latest.json 原子切换条件；根据 P02 确认公网 HTTP 校验条件。能力预检不等于已经执行这些写操作，正式步骤仍须逐一验证。

保存或输出每项 PASS/BLOCKED/NOT_RUN/SKIPPED 及证据，注明目标版本、当前源码/工作区、产物哈希、服务器和检查时间，不记录凭据。全部必检 PASS 才转入第二阶段；预检报告使用“整体、服务器、更新地址、本地发布文件、Git、GitHub、测试、发现的问题、是否可以直接正式收尾”的结构。发生 BLOCKED 时必须说明当前阶段、已发生修改、尚未执行项和建议处理方式，随后结束本轮。

## 5. 第二阶段：正式发布顺序（仅第一阶段全部 PASS 后执行）

进入本节必须已有本次第一阶段的全 PASS 结论。严格按以下顺序推进，每一步成功才进入下一步；已完成步骤先验证，不重复制造 commit/tag/Release。预检之后源代码或外部状态改变时，先重新检查受影响项目，不能直接使用失效的 PASS。

1. **检查 Git 工作区**：git status --short --branch、git diff、git diff --cached，核对分支和 remote。
2. **确认修改归属**：审阅本版源码、文档及脱敏测试，排除真实样本、凭据、构建和用户运行数据。
3. **运行回归测试**：按第 4 节执行，记录数量；必要的真实样本兼容性测试也必须通过。
4. **检查 VERSION**：规范三段数字，等于用户目标，相对公网正式版本递增；检查同名 tag/Release 是否冲突。
5. **核验并复用 Setup / Portable ZIP**：复用第一阶段已通过的有效产物，不重复构建。若产物丢失、源码已变或发现构建无效，停止第二阶段并标记 BLOCKED；需要构建时由单独授权的准备步骤在 Web 目录执行 ./build-release.ps1，完成后重新预检，不直接跳回提交/发布。部分归档存在时检查日志和来源，不删除或覆盖已归档文件整批重建。
6. **计算发布文件 SHA256**：分别记录 Setup/ZIP 路径、字节数、SHA256，核对中文与英文副本。准备本地 latest.json（第 7 节），尚不改服务器正式元数据。
7. **Git commit**：仅显式暂存审核过的本版文件，提交信息 Release vX.X.X。已有匹配提交则复用；提交信息相同不够，需核对内容与构建来源。
8. **创建 Git tag**：vX.X.X 指向本版提交。已有 tag 比较目标提交，冲突则停，不能删除或强制移动。
9. **推送 master**：git push origin master。非 fast-forward 失败时停止，不强推、不擅自 merge/rebase。
10. **推送 tag**：git push origin vX.X.X，核对远端 master/tag 与本地提交一致。
11. **创建/复用 GitHub Release**：tag 为 vX.X.X，标题“发票整理工具 vX.X.X”，正文简述本次变化。建议先建 draft，使用 --verify-tag 保证 tag 已存在。
12. **上传 Setup**：英文 asset 名及中文 label。已有同名附件检查大小/hash，一致就复用，不一致停止，不自动 --clobber。
13. **上传 Portable ZIP 并完成 GitHub 正式发布**：当前项目两种产物均必需；若将来取消 Portable，须用户明确决定并先更新本文件与构建配置。核对附件大小/hash后将 draft 发布为非 prerelease 的最新正式 Release。GitHub asset digest 与本地必须一致；API 无 digest 时必须完整下载算哈希。
14. **发布到正式更新服务器**：按第 6 节临时上传、校验，再移入 releases。移动前本地/GitHub/服务器临时文件 SHA256 必须三方一致，保留所有历史安装包。
15. **更新 latest.json**：仅在对应正式 Setup 已存在且 GitHub 正式 Release 完成后，按第 6、7 节临时生成、验证、原子替换。
16. **验证服务器文件 SHA256**：重新核对正式 releases 下 Setup 的字节数/hash 与正式 JSON，不能只校验临时文件。
17. **验证公网 latest.json**：正式 HTTPS URL 必须 HTTP 200，JSON 可解析，五字段与审核内容一致，无第三方域名/废弃地址跳转。
18. **验证 Setup 下载**：download_url HTTP 200，Content-Length 与本地字节数一致，完整下载重算 SHA256；仅 HEAD 200 不算完成。
19. **最终检查 Git clean**：git status --porcelain 为空，复核远端分支/tag、GitHub 和服务器后报告；只清理本次临时文件。

build-release.ps1 不自动执行第 7–19 步；Codex 必须继续完成，不能将“构建成功”称为“发布完成”。

## 6. 服务器临时上传、校验与原子切换

1. 核对 alias、root 登录、目录写权限、当前 latest.json 及同版本文件，不连接旧 IP。
2. 英文 Setup 先上传至 /var/www/invoice-organizer/tmp/invoice-organizer-Setup-vX.X.X.exe.part。同名临时文件存在时先核对来源/hash，不覆盖未知文件。
3. 服务器执行 sha256sum 和 stat -c %s 核对临时安装包。与本地和 GitHub 一致后设权限 644，在同一文件系统移动到 /var/www/invoice-organizer/releases/invoice-organizer-Setup-vX.X.X.exe。正式目标已存在且一致可复用，不一致则停，禁止覆盖已发布版本。
4. 正式安装包存在且可读后，把已审核的本地 JSON 上传为 /var/www/invoice-organizer/latest.json.tmp。已有 tmp 先检查是否属于本次中断发布，不覆盖未知内容。
5. 用 python3 -m json.tool /var/www/invoice-organizer/latest.json.tmp 验证语法，再校验第 7 节全部字段、版本、英文 URL、真实 Setup 哈希和历史 changelog。语法通过不等于内容正确。
6. 确认正式 latest.json 未被其他任务更新为更高/不同版本，为临时文件设 644，通过同目录原子重命名（例如 mv -T latest.json.tmp latest.json）替换。不先删除正式 JSON，不边写边覆盖正式文件。
7. 执行第 16–18 步验证。HTTPS、哈希或元数据校验失败时报告阶段与影响，不使用 HTTP/旧 IP 回退掩盖问题。
8. 清理本次已知来源的 .part/.tmp；移动成功则原路径自然消失。不得递归清理 tmp/releases，不删除其他任务的临时文件或历史版本。

## 7. latest.json 与累计更新说明

latest.json 是客户端检查更新的正式依据，永远只指向当前正式最新版本的完整 Setup，而非补丁。允许跨版本安装，不要求用户逐版升级。

每次正式发布必须包含五字段，结构如下（占位符禁止原样上传）：

~~~json
{
  "version": "X.X.X",
  "notes": "按版本分段的累计更新说明，兼容只认识 notes 的旧客户端",
  "download_url": "https://update.jaystash.online/invoice-organizer/releases/invoice-organizer-Setup-vX.X.X.exe",
  "sha256": "实际安装包的64位小写十六进制SHA256",
  "changelog": [
    {"version": "历史版本号", "notes": ["经核实的该版本更新事项"]},
    {"version": "X.X.X", "notes": ["本次版本更新事项"]}
  ]
}
~~~

- version 与 VERSION/Release/tag 一致，不带 v；sha256 来自本次构建实际安装包，不复用历史哈希。
- download_url 仅使用正式 HTTPS 域名和英文安装包名，不允许第三方域名或旧 IP。
- changelog 按数字版本升序排列，每个 version 唯一、合法且不高于最新版本，notes 为非空纯文本字符串数组。保留历史，再追加当前条目，不丢历史、不编造说明。
- 顶层 notes 从同一份 changelog 生成，按“【vX.X.X】”分段，覆盖旧客户端所需的累计更新内容，不能只写本次一句话。
- v1.0.21 及之后客户端筛选“本地版本 < 条目版本 <= 最新版本”；旧客户端继续读顶层 notes。客户端兼容缺少 changelog 的旧 JSON，但新正式发布必须包含完整五字段。
- GitHub Release 正文只需写本次变化，无须复制完整累计 notes。更新文本不执行任何代码。
- 发布 JSON 必须符合现有客户端限制：UTF-8 总字节数不超过 65,536；顶层 notes 不超过 20,000 个字符；changelog 不超过 100 条；每条 notes 为非空列表，单段文本长度为 1–2,000 个字符。发布前应使用 app/update_client.py 的解析器验证，并单独检查总字节数与版本筛选结果。将来历史记录接近限制时，停止并提出客户端兼容性方案，不擅自删历史、截断说明或发布客户端无法读取的 JSON。
- 历史说明优先取自正式 latest.json 的 changelog，再核对历史发布记录、GitHub Releases 和对应提交。旧 JSON 缺少 changelog 时从可靠来源补全，不能因此丢掉历史；无法可靠恢复时停止报告，不猜写或先发布不完整 JSON。

首次按本规范发布的迁移注意：建立本规范时，公网 v1.0.22 的 JSON 只有 version/notes/download_url/sha256，尚无 changelog。下一次发布需恢复历史说明并生成累计 notes。更新本文档本身不授权修改已发布的 v1.0.22 文件或历史安装包。

## 8. 重入、冲突与异常处理

- 检查已有 commit/tag/Release/安装包的目标提交、版本、大小、SHA256、draft 状态及服务器元数据；一致则继续缺失步骤。
- draft 已有正确附件时只需核验并发布，不重复上传。正式 Release 已存在且完全一致则复用，不能悄悄换一组同版本二进制。
- 版本不一致、源码归属不明、tag 错误、同版本哈希冲突、凭据/主机密钥异常、测试/上传/HTTP 失败时，停止在当前阶段，保留已有成果和历史版本。
- 不为“完成发布”擅自修改业务、UI、代理、Nginx 或降低安全校验。需要新授权或用户决策时说明后等待。
- 失败报告必须写清：问题是什么；进行到哪一步；哪些本地/GitHub/服务器修改已发生；哪些正式状态尚未切换；建议如何恢复/续跑。
- 不自动删除已有 Release/tag/commit 重试。正式 latest.json 已切换后的异常不能隐瞒或擅自回退，须报告影响并请求必要决策。

## 9. 最终完成标准与报告

只有以下条件全部满足，才能报告“vX.X.X 发布完成”：

- [ ] 全部回归测试和必要样本兼容性测试通过。
- [ ] 本次第一阶段所有必检预检项 PASS，无 BLOCKED 或 NOT_RUN；允许的桌面验证 SKIPPED 有明确原因。
- [ ] VERSION 与产物、tag/Release 一致。
- [ ] Release vX.X.X commit 完成，tag 指向正确提交。
- [ ] master、tag 均已 push，远端目标正确。
- [ ] GitHub Release 正式发布，不是 draft/prerelease。
- [ ] Setup 和当前提供的 Portable ZIP 均已发布。
- [ ] 服务器正式 Setup 存在，历史版本保留。
- [ ] 本地/GitHub/服务器 Setup SHA256 一致，ZIP 本地/GitHub 哈希一致。
- [ ] latest.json 五字段正确、历史 changelog 完整，指向实际存在的最新正式 Setup。
- [ ] 公网 latest.json HTTP 200、JSON 可解析且版本正确。
- [ ] Setup 公网 HTTP 200、Content-Length 正确、完整下载哈希一致。
- [ ] Git 工作区 clean，本次临时发布文件已清理。

最终报告至少列出：VERSION；测试与 skipped 原因；commit 哈希；tag/push；本地 Setup/ZIP 路径、字节数、SHA256；GitHub Release URL 和附件；服务器 Setup URL；三方哈希；公网 JSON/Setup 验证；历史版本保留；Git clean 状态；未完成事项。

任何一项未完成，必须明确写“发布未完成”及缺失项，不以“基本完成”“构建完成”替代发布成功。
