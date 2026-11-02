# 命令行参考

以下命令在仓库根目录运行，使用 `setup.ps1` 创建的虚拟环境。

## 示例

启动 GUI，并指定源目录：

```powershell
.\.venv\Scripts\python.exe app.py --source "D:\health-archive\HUAWEI_HEALTH"
```

只转换最多三条代表性样本：

```powershell
.\.venv\Scripts\python.exe app.py --cli --source "D:\health-archive\HUAWEI_HEALTH" --output ".\exported_fit\samples" --samples
```

转换全部记录：

```powershell
.\.venv\Scripts\python.exe app.py --cli --source "D:\health-archive\HUAWEI_HEALTH" --output ".\exported_fit\all"
```

## 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--source PATH` | CLI 为 `HUAWEI_HEALTH` | 源目录或单个运动明细 JSON 文件；GUI 也可通过对话框选择目录 |
| `--cli` | 关闭 | 不启动窗口，在命令行中扫描并转换 |
| `--output PATH` | `exported_fit` | CLI 的输出目录；GUI 使用界面中选择的输出目录 |
| `--samples` | 关闭 | CLI 只导出代表性样本；输出位置完全由 `--output` 指定 |
| `--coord MODE` | `auto` | CLI 的坐标处理方式；GUI 使用界面中选择的方式 |
| `--help` | — | 显示帮助信息 |

输出目录应位于源目录之外。CLI 在转换失败、源目录无可转换记录或运行错误时返回退出码 `1`，其余成功情况返回 `0`。

## 坐标方式

| MODE | 行为 |
| --- | --- |
| `auto` | 优先读取明确的 GCJ-02 / WGS-84 标记；无标记但来源是 AMAP 时假设为 GCJ-02，并在报告中说明；其他未知坐标系省略 GPS |
| `gcj02` | 指定源坐标为 GCJ-02，转换为 WGS-84；范围外坐标保持原值 |
| `wgs84` | 指定源坐标为 WGS-84，保留原坐标 |
| `omit` | 不导出 GPS，保留其余可用传感器数据和运动汇总 |

## 输出文件

- `日期_时间_运动类型_摘要.fit`：每次运动一个 FIT。
- `export_manifest.json`：成功导出文件的指纹、哈希和限制说明，用于识别重复导出。
- `conversion_report_*.json`：本次任务的成功、跳过、失败、取消状态及各条记录的说明。
- `converter_settings.json`：GUI 在应用目录保存的源路径、输出路径和坐标选项。

报告可能包含源文件路径、运动日期和记录 ID。默认不纳入 Git。
