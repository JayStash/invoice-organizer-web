# 版本发布流程

所有正式版本统一以项目根目录的 `VERSION` 为版本号来源，格式必须为 `X.X.X`。修改版本后，在 `invoice-organizer-web` 目录执行：

```powershell
.\build-release.ps1
```

脚本会构建 PyInstaller onedir 便携版、Inno Setup 安装包，并归档到：

```text
D:\AI项目\智能发票整理\dist\releases\vX.X.X\
```

## 本地归档

本地版本归档始终保留中文文件名：

```text
发票整理工具-Windows-x64-vX.X.X.zip
发票整理工具-Setup-vX.X.X.exe
```

ZIP 必须包含完整的 PyInstaller onedir 发布目录，不能只包含主 EXE。已经发布的版本目录不得覆盖或重建。

## GitHub Release

GitHub Release 实际上传的资产必须使用英文文件名：

```text
invoice-organizer-Windows-x64-vX.X.X.zip
invoice-organizer-Setup-vX.X.X.exe
```

Release 正文中的中文显示说明统一为：

```text
发票整理工具 vX.X.X 便携版
发票整理工具 vX.X.X 安装版
```

不要重命名本地 `dist\releases\vX.X.X` 中的中文归档文件；上传时使用脚本另行生成的英文副本。

`build-release.ps1` 会自动在以下独立目录生成这两个英文副本，可直接选择它们上传：

```text
D:\AI项目\智能发票整理\dist\publish\vX.X.X\
```

## 自建更新服务器

更新服务器上的安装包必须使用英文文件名：

```text
invoice-organizer-Setup-vX.X.X.exe
```

服务器文件位置为：

```text
/invoice-organizer/releases/invoice-organizer-Setup-vX.X.X.exe
```

`latest.json` 中的 `download_url` 必须引用同一个英文文件名，不得使用中文文件名或第三方域名：

```json
{
  "version": "X.X.X",
  "notes": "版本更新说明",
  "download_url": "https://update.jaystash.online/invoice-organizer/releases/invoice-organizer-Setup-vX.X.X.exe",
  "sha256": "安装包的 64 位 SHA256"
}
```

发布前必须对实际上传的安装包重新计算 SHA256，并确保与 `latest.json` 完全一致。更新 `latest.json` 前，应先确认对应安装包已经上传到服务器。

## 发布检查

1. 更新 `VERSION`，不要在其他文件中手工维护版本号。
2. 运行测试并执行 `build-release.ps1`。
3. 核对本地归档目录和两个中文文件名。
4. 从 `dist\publish\vX.X.X` 选取 GitHub 英文文件，并使用脚本输出的中文显示说明。
5. 从同一目录选取英文 Setup 文件用于更新服务器。
6. 计算服务器安装包 SHA256，再更新 `latest.json`。
7. 完成本地 commit 和 tag 后，由维护者决定是否执行远程发布。

构建脚本只负责本地构建和归档，不执行 GitHub 上传、`git push` 或服务器操作。
