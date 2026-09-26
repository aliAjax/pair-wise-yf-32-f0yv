# 器官分配与转运协调系统

Python 标准库独立项目。系统按器官类型、血型、地域、医疗匹配、紧急程度和等待时间排序候选患者，并管理提出、接受、转运、交接、植入或撤回流程。器官过期后所有继续流转操作都会被阻止，全部状态变化写入审计记录。

## 运行

```bash
python3 app.py --db organ_allocation.db
```

默认监听 `127.0.0.1:8203`，首页 `/`，健康检查 `/health`。

身份头：`X-User-Id`、`X-Role`。角色为 `viewer`、`hospital`、`coordinator`、`allocation_officer`、`auditor`；医院角色还需 `X-Hospital`。

## 主要接口

- `POST /api/donors`、`POST /api/candidates`：登记器官与候选患者。
- `GET /api/donors/{id}/ranking`：查看兼容候选排序。
- `POST /api/allocations`：提出唯一分配。
- `POST /api/allocations/{id}/accept`、`withdraw`：医院确认或撤回。
- `POST /api/allocations/{id}/clearance`：接收医院提交术前放行（交叉配型结果 + 主刀可手术时段）。
- `POST /api/allocations/{id}/clearance-backfill`：协调台补录放行记录（可指定提交时刻）。
- `GET /api/allocations/{id}/clearance`：查看该分配全部放行记录。页面入口 `/clearance`。
- `POST /api/allocations/{id}/transit`、`delay`：冷链转运和延误上报。
- `POST /api/allocations/{id}/handoff`、`handoff-accept`：来源医院发起、接收医院确认。
- `POST /api/allocations/{id}/implant`：确认植入。
- `GET /api/allocations/{id}/audit`、`GET /api/state`：完整审计和权限视图。

## 术前放行

分配提出后、医院确认接受前必须通过术前放行。接收医院提交 `crossmatch_compatible`（布尔）和 `surgeon_available_at`（主刀最早可开台的 ISO 8601 时刻，缺项可省略）。判断规则（`clearance.py`，与存储、页面分开维护）：

- 缺交叉配型结果或主刀时段 → 标记缺项，不放行；
- 交叉配型不合格 → 不放行；
- 提交时刻晚于分配提出后 120 分钟（`REVIEW_DEADLINE_MINUTES`）→ 复核超时，不放行；
- 主刀开台距器官过期不足 60 分钟（`MIN_SURGERY_WINDOW_MINUTES`）→ 时段不足，不放行。

未通过时分配保持 `proposed`（待接收），返回原因与缺项；只有最新记录为 approved 才能 `accept`，从源头阻止运输提前启动。每次提交（含未通过）都保留提交人、结果、时刻；协调台可补录并查看全部历史，`viewer` 不可查看。旧分配没有放行记录时，分配视图和 `/api/state` 列表标为“待补录”，补录后消失。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 主要局限

血型兼容与评分是演示规则，不包含 HLA 分型、器官大小、病程、儿科差异和真实移植网络规则。医院身份使用请求头模拟，SQLite 环境适合原型，不处理跨机构身份信任、远程患者隐私协议和真实冷链设备接入。
