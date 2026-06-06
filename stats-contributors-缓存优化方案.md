# `/stats/contributors` 缓存优化方案可行性分析

> 目标：减少 `/repos/{owner}/{repo}/stats/contributors` 的 REST API 调用次数，通过本地缓存 + 增量更新机制避免对未变更仓库的重复请求。

---

## 1. 现状分析

### 当前调用方式

`lines_changed` 属性（`github_stats.py:484-510`）对 `self.repos` 中的**每个仓库**逐一调用：

```
for repo in await self.repos:
    r = await self.queries.query_rest(f"/repos/{repo}/stats/contributors")
```

- 仓库数 N → N 次 REST 请求
- 每次请求可能触发 HTTP 202 重试（最坏 238 秒/次）
- 并发信号量限制为 10

### 当前 GraphQL 查询已有的信息

`repos_overview()` 查询（`github_stats.py:127-205`）已经按 `UPDATED_AT` 排序，但**未请求**以下字段：
- `pushedAt` — 最后一次 push 时间（用于判断是否有新代码提交）
- `isPrivate` — 是否为私有仓库（用于区分缓存策略）

这些字段在 GitHub GraphQL Schema 的 `Repository` 类型上均可用，且查询已使用 `orderBy: {field: UPDATED_AT}` 证明该字段存在。

---

## 2. 方案概述

```
                    ┌─────────────────────────────────┐
                    │     GraphQL repos_overview       │
                    │  (新增 updatedAt + isPrivate)    │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │       读取本地缓存文件            │
                    │    cache/{username}.json           │
                    └──────────────┬──────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
     ┌────────▼────────┐  ┌───────▼────────┐  ┌────────▼────────┐
     │  公有仓库         │  │  公有仓库       │  │  私有仓库        │
     │  无更新(10天内)   │  │  有更新/无缓存  │  │  全部重新请求     │
     │  → 使用缓存       │  │  → 请求API      │  │  → 不缓存到本地   │
     │  → 0次REST请求    │  │  → 更新缓存      │  │                  │
     └─────────────────┘  └────────────────┘  └─────────────────┘
```

---

## 3. 可行性逐项分析

### 3.1 获取仓库更新时间 — 可行

**方式**：在现有 GraphQL `repos_overview()` 查询的 `nodes` 中新增 `updatedAt` 和 `isPrivate` 字段。

**当前查询**（`github_stats.py:150-165`）：
```graphql
nodes {
  nameWithOwner
  stargazers { totalCount }
  forkCount
  languages(first: 10, ...) { ... }
}
```

**修改为**：
```graphql
nodes {
  nameWithOwner
  pushedAt         # 新增：最后 push 时间，用于判断是否有新代码
  isPrivate        # 新增：区分公有/私有仓库
  stargazers { totalCount }
  forkCount
  languages(first: 10, ...) { ... }
}
```

> 使用 `pushedAt` 而非 `updatedAt`，因为只有代码推送才影响 `/stats/contributors` 的数据。

**影响**：
- 不增加 API 请求次数（复用现有查询）
- 响应体略微增大（每个仓库多 2 个字段）
- `repositoriesContributedTo` 的 `nodes` 也需同步新增

**结论**：✅ 零额外开销，完全可行。

---

### 3.2 本地缓存结构 — 可行

**两种方案对比**：

| 方案 | 存储路径 | 优点 | 缺点 |
|------|---------|------|------|
| 按仓库分文件 | `cache/contributors/{owner}_{repo}.json` | 粒度细，冲突少 | 文件数量多，100 个仓库 = 100 个文件 |
| **按用户单文件**（推荐） | `cache/{username}.json` | 文件少，管理简单 | 并行写入可能冲突 |

**推荐使用按用户单文件方案**，一个用户的所有仓库数据存在同一个 JSON 文件中（`cache/{username}.json`），以 `owner/repo` 为 key：

```json
{
  "yansheng836/project-a": {
    "fetchedAt": "2026-06-06T00:05:00Z",
    "pushedAt": "2026-06-04T12:30:00Z",
    "additions": 4520,
    "deletions": 1830
  },
  "yansheng836/project-b": {
    "fetchedAt": "2026-06-06T00:05:00Z",
    "pushedAt": "2026-05-20T08:00:00Z",
    "additions": 1200,
    "deletions": 500
  }
}
```

**Git 跟踪**：
- 缓存文件提交到仓库（与 `generated/` 目录一起），供下次 Actions 运行时读取
- `.gitignore` 无需修改（当前未忽略 `cache/` 目录）

**结论**：✅ 单文件方案结构简单，100 个仓库 ≈ 10-20 KB，可直接 git 跟踪。

---

### 3.3 增量更新判断逻辑 — 可行

**判断条件**：仓库是否需要重新请求 `/stats/contributors`

```
需要更新 = 以下任一条件为真：
  1. 缓存中无此仓库记录
  2. 仓库 pushedAt > 缓存中的 fetchedAt（仓库有新 push）
  3. 设置了 CACHE_EXPIRY_DAYS 且缓存超过该天数（强制刷新兜底）
```

**环境变量 `CACHE_EXPIRY_DAYS`**：

| 值 | 行为 |
|-----|------|
| 未设置（默认） | 仅依赖 `pushedAt > fetchedAt` 判断，不设时间兜底 |
| `7` | 缓存超过 7 天的仓库强制刷新，对齐按周聚合的周期 |
| `10` | 缓存超过 10 天的仓库强制刷新，留一定余量 |
| `0` | 每次运行都强制刷新所有仓库（等同于禁用缓存） |

建议在 workflow 中设置 `CACHE_EXPIRY_DAYS: 7`，理由：
- `/stats/contributors` 数据按周聚合，7 天刚好覆盖一个周期
- 如果某周没有 push，7 天后仍会刷新，确保本周数据被"定稿"入库
- 防止 `pushedAt` 因 GitHub 内部缓存等原因未及时更新导致的数据陈旧

**注意**：使用 `pushedAt`（最后 push 时间）比 `updatedAt` 更准确，因为：
- `updatedAt` 包括 metadata 变更（如修改 description、settings），这些不影响贡献统计
- `pushedAt` 只在有新代码推送时变化，与 `/stats/contributors` 数据直接相关

**结论**：✅ 逻辑清晰，判断依据可靠，环境变量提供灵活控制。

---

### 3.4 公有 vs 私有仓库的区分处理 — 可行

GraphQL 响应中已包含 `isPrivate` 字段，可直接用于分支判断：

| 类型 | 缓存到本地 | 读取缓存 | 说明 |
|------|-----------|---------|------|
| 公有仓库 | ✅ 写入 `cache/{username}.json` | ✅ 符合条件时使用 | 无安全风险，数据已公开 |
| 私有仓库 | ❌ 不写入文件 | ❌ 每次重新请求 | 防止泄漏代码量等敏感信息 |

**私有仓库的内存缓存**：
- 私有仓库数据仍可在单次运行内使用内存缓存（`self._lines_changed`），避免同一运行中重复请求
- 只是不持久化到 git 仓库

**结论**：✅ 通过 `isPrivate` 字段自然区分，无额外复杂度。

---

### 3.5 缓存的首次构建 — 可行

**首次运行**（无缓存文件时）：
- 所有仓库都需要调用 `/stats/contributors`
- 请求完成后将公有仓库数据写入缓存文件
- 行为与当前一致，无退化

**后续运行**：
- 读取缓存，对比 `pushedAt`
- 仅对有更新的仓库和私有仓库发起请求
- 更新缓存文件并提交

**结论**：✅ 首次无退化，后续逐步优化。

---

### 3.6 `/traffic/views` 是否也适用同样优化 — 部分适用但不建议

`/traffic/views` 返回的是**近 14 天**的浏览量数据，具有以下特点：
- 数据是时间窗口性的，缓存过期快
- 即使仓库没有新 push，浏览量也会变化
- 缓存收益小（仍需频繁更新）

**结论**：❌ 不建议对 `/traffic/views` 做缓存优化。该端点不太会触发 202 重试，耗时远低于 `/stats/contributors`。

---

## 4. 预估优化效果

以 50 个仓库为例（40 公有 + 10 私有），每日运行：

| 场景 | 当前方案 | 优化后 | 节省 |
|------|---------|--------|------|
| 首次运行 | 50 次 REST | 50 次 REST + 写缓存 | 0% |
| 每日无更新 | 50 次 REST | 10 次 REST（仅私有） | 80% |
| 每日 3 个仓库有更新 | 50 次 REST | 13 次 REST（10 私有 + 3 公有有更新） | 74% |
| 每日 10 个仓库有更新 | 50 次 REST | 20 次 REST（10 私有 + 10 公有有更新） | 60% |

**202 重试的节省更显著**：如果公有仓库已缓存，即使它们触发 202 重试也不会被请求，直接跳过。

---

## 5. 潜在风险与注意事项

### 5.1 `pushedAt` 与实际贡献数据的时差

- `/stats/contributors` 是按周聚合的统计数据
- 如果用户在本周内有 push，但缓存的 `fetchedAt` 也在本周，则缓存的周数据可能不完整
- **缓解**：除检查 `pushedAt` 外，额外检查 `fetchedAt` 是否在当前周内（即周一之后），如果是则强制刷新

### 5.2 缓存文件冲突

- 如果手动修改了缓存文件或并行 Actions 运行，可能产生 git 冲突
- **缓解**：使用 `git pull --rebase` 或在 workflow 中加锁

### 5.3 缓存文件体积

- 每个仓库的缓存约 100-200 bytes
- 100 个仓库 ≈ 10-20 KB，可忽略不计

### 5.4 `repositoriesContributedTo` 的权限问题

- 对于 contributedTo 的仓库，用户可能没有 push 权限
- 这些仓库的 `/stats/contributors` 请求可能返回 403
- **注意**：即使有缓存，如果仓库从 contributedTo 变为不再贡献，缓存记录应被清理

---

## 6. 需要修改的代码文件

| 文件 | 修改内容 |
|------|---------|
| `github_stats.py:128-211` | `repos_overview()` 查询新增 `pushedAt`、`isPrivate` 字段 |
| `github_stats.py:356-366` | `get_stats()` 中解析并存储每个仓库的 `pushedAt`、`isPrivate` |
| `github_stats.py:497-597` | 新增缓存读写方法 + `lines_changed` 属性加入缓存逻辑和增量判断 |
| `generate_images.py:123-134` | 读取 `CACHE_EXPIRY_DAYS` 环境变量，传入缓存过期天数 |
| `.github/workflows/main.yml:46` | 新增 `CACHE_EXPIRY_DAYS: 7` 环境变量 |

---

## 7. 结论

| 评估维度 | 结论 |
|----------|------|
| 技术可行性 | ✅ 完全可行，利用现有 GraphQL 字段 |
| 实现复杂度 | 🟡 中等，需修改查询 + 新增缓存读写逻辑 |
| 性能收益 | ✅ 显著，公有仓库占比高时可减少 60-80% REST 请求 |
| 安全性 | ✅ 私有仓库不缓存，无泄漏风险 |
| 维护成本 | 🟡 低，缓存文件自动管理，需处理边缘情况 |
| 首次运行退化 | ✅ 无退化，首次行为与当前一致 |

**已实施**。修改了 `github_stats.py`、`generate_images.py`、`.github/workflows/main.yml` 共 3 个文件。
