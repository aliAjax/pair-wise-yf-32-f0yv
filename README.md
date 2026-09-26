# 器官分配与转运协调系统

Python 标准库独立项目。系统按器官类型、血型、地域、医疗匹配、紧急程度和等待时间排序候选患者，并管理提出、术前放行、接受、转运、交接、植入或撤回流程。器官过期后所有继续流转操作都会被阻止，全部状态变化写入审计记录。

## 术前放行

接受分配前必须通过术前放行：接收医院提交交叉配型结果和主刀可手术时段，系统按器官剩余时间判断是否来得及。结果不合格、复核超时（默认 12 小时有效期）或时段不足时，分配保持待接收并返回缺项说明。每条放行记录保留提交人、结果和时刻；协调台（coordinator）可以补录和查看历史；没有记录的分配标记为 `pending`（待补）。判断、记录和页面分开维护：

- `release_rules.py`：放行判断规则（纯函数，提交时和接受时复核共用）。
- `release_store.py`：放行记录表结构和读写。
- `static/release.html`：放行提交、补录和查看页面。

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
- `POST /api/allocations/{id}/release`：接收医院提交术前放行（协调台可补录）。
- `GET /api/allocations/{id}/release`：查看最新放行记录和提交历史。
- `POST /api/allocations/{id}/accept`、`withdraw`：医院确认（需放行通过）或撤回。
- `POST /api/allocations/{id}/transit`、`delay`：冷链转运和延误上报。
- `POST /api/allocations/{id}/handoff`、`handoff-accept`：来源医院发起、接收医院确认。
- `POST /api/allocations/{id}/implant`：确认植入。
- `GET /api/allocations/{id}/audit`、`GET /api/state`：完整审计和权限视图。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 主要局限

血型兼容与评分是演示规则，不包含 HLA 分型、器官大小、病程、儿科差异和真实移植网络规则。医院身份使用请求头模拟，SQLite 环境适合原型，不处理跨机构身份信任、远程患者隐私协议和真实冷链设备接入。
