# Huawei Health to FIT

将华为运动健康导出归档中的运动明细 JSON 转换为标准 FIT Activity 文件。提供中文桌面 GUI 和命令行入口，每次运动生成一个 FIT，供支持此格式的平台导入。

## 功能

- 自动扫描运动明细分片、按记录 ID 去重并预览运动。
- 按运动类型、日期筛选，导出所选记录或全部筛选结果。
- 选择有轨迹、有明显暂停、无轨迹的代表记录作为测试样本。
- 保存已有心率、步频、海拔、可对齐速度及运动汇总。
- 选择轨迹坐标处理方式；逐条解码并校验 FIT CRC。
- 后台转换、进度显示、取消、重复导出跳过，以及 JSON 结果报告。

转换在本地完成。工具负责生成 FIT，Zepp 手机端的实际导入效果需先用样本确认。

## 在 Windows 上运行

需要 Python 3.10 或更高版本及 Tkinter。当前版本已在 Windows、Python 3.14 上验证。首次安装依赖需要网络。

1. 将仓库下载到本地，在仓库目录打开 PowerShell。
2. 创建虚拟环境并安装依赖：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
   ```

   如果 Python 没有加入 PATH，可指定安装路径：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -PythonExe "C:\path\to\python.exe"
   ```

   上述 ExecutionPolicy 参数仅对该次 PowerShell 进程生效。

3. 双击 `Start GUI.cmd`，或运行：

   ```powershell
   .\.venv\Scripts\python.exe app.py
   ```

4. 选择华为导出的 `HUAWEI_HEALTH` 目录，或其中的运动明细目录，点击“扫描记录”。
5. 选择源目录以外的输出位置，先点击“导出测试样本”。样本位于输出目录的 `samples` 子目录。
6. 在 Zepp 中试导入样本并核对日期、距离、时长、心率和轨迹，再导出全部筛选结果。

若使用已打包的 Windows EXE，可直接双击运行，无需单独安装 Python。

## 打包 Windows EXE

在 Windows 上执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -BuildTools
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

生成的 `HuaweiHealthToFIT.exe` 位于仓库根目录和 `dist` 目录。分发时附带 `GARMIN_FIT_SDK_LICENSE.txt`。

## 仓库内容

```text
app.py                     GUI / CLI 入口
huawei_fit/core.py         数据扫描、字段映射、FIT 编码、校验和导出
huawei_fit/gui.py          中文 Tkinter 界面
requirements.txt          运行依赖
requirements-build.txt    打包依赖
setup.ps1                 Windows 环境安装
Start GUI.cmd             Windows 启动入口
build.ps1                 Windows 打包脚本
docs/cli.md               命令行和坐标选项参考
docs/conversion.md        转换规则、已知限制和验证范围
GARMIN_FIT_SDK_LICENSE.txt 第三方 SDK 许可原文
```

源码仓库不附带个人健康归档、运动样本或转换结果。`.gitignore` 默认排除 JSON、FIT、健康表格、EXE、虚拟环境和构建产物；本地设置与结果报告也不会被正常的 `git add` 纳入。

如需发布可执行程序，可将打包产物作为单独的发行附件。不要对个人数据使用 `git add -f`。

项目依赖 Garmin FIT SDK，其许可原文见随附文件；该文件不代表本项目其他源码的许可证。
