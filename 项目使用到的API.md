# GitHub Stats 项目 API 分析

> 项目 fork 自 [jstrieb/github-stats](https://github.com/jstrieb/github-stats)，通过 GitHub Actions 每日定时运行，获取用户的 GitHub 统计数据并生成两张 SVG 图片（`overview.svg` 和 `languages.svg`），嵌入到个人主页 README 中。

---

## 1. 使用的 API 总览

| API | 端点 | 方法 | 用途 | 调用位置 |
|-----|------|------|------|----------|
| GitHub GraphQL v4 | `https://api.github.com/graphql` | POST | 获取仓库列表、star/fork 数、语言统计、贡献日历 | `github_stats.py:46-50` |
| GitHub REST v3 | `/repos/{owner}/{repo}/stats/contributors` | GET | 获取每个仓库的代码增删行数（按周统计） | `github_stats.py:494` |
| GitHub REST v3 | `/repos/{owner}/{repo}/traffic/views` | GET | 获取每个仓库近 14 天的页面浏览量 | `github_stats.py:523` |

所有请求共用同一个 `ACCESS_TOKEN` 进行认证：
- GraphQL：`Authorization: Bearer {token}`（`github_stats.py:42`）
- REST：`Authorization: token {token}`（`github_stats.py:82`）

---

## 2. 各 API 请求/响应详细示例

### 2.1 GraphQL — `repos_overview()`：获取仓库概况

**代码位置**：`github_stats.py:127-205`（查询定义）、`github_stats.py:305-382`（分页调用）

#### 请求

```
POST https://api.github.com/graphql
Authorization: Bearer ghp_xxxxxxxxxxxx
Content-Type: application/json

{
  "query": "{ viewer { login, name, repositories(first: 100, orderBy: {field: UPDATED_AT, direction: DESC}, isFork: false, after: null) { pageInfo { hasNextPage endCursor } nodes { nameWithOwner stargazers { totalCount } forkCount languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } } } } repositoriesContributedTo(first: 100, includeUserRepositories: false, orderBy: {field: UPDATED_AT, direction: DESC}, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW] after: null) { pageInfo { hasNextPage endCursor } nodes { nameWithOwner stargazers { totalCount } forkCount languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } } } } } }"
}
```

#### 响应（200 OK）

```json
{
  "data": {
    "viewer": {
      "login": "yansheng836",
      "name": "Yan Sheng",
      "repositories": {
        "pageInfo": {
          "hasNextPage": false,
          "endCursor": "Y3Vyc29yOnYyOpHOAAAAAA=="
        },
        "nodes": [
          {
            "nameWithOwner": "yansheng836/project-a",
            "stargazers": { "totalCount": 12 },
            "forkCount": 3,
            "languages": {
              "edges": [
                { "size": 45000, "node": { "name": "Python", "color": "#3572A5" } },
                { "size": 12000, "node": { "name": "JavaScript", "color": "#f1e05a" } },
                { "size": 3000,  "node": { "name": "HTML",      "color": "#e34c26" } }
              ]
            }
          },
          {
            "nameWithOwner": "yansheng836/project-b",
            "stargazers": { "totalCount": 5 },
            "forkCount": 1,
            "languages": {
              "edges": [
                { "size": 20000, "node": { "name": "Go", "color": "#00ADD8" } }
              ]
            }
          }
        ]
      },
      "repositoriesContributedTo": {
        "pageInfo": {
          "hasNextPage": false,
          "endCursor": "Y3Vyc29yOnYyOpHOABBBB=="
        },
        "nodes": [
          {
            "nameWithOwner": "other-user/some-project",
            "stargazers": { "totalCount": 150 },
            "forkCount": 40,
            "languages": {
              "edges": [
                { "size": 80000, "node": { "name": "TypeScript", "color": "#3178c6" } }
              ]
            }
          }
        ]
      }
    }
  }
}
```

#### 代码提取的字段

| 代码 | 提取路径 |
|------|----------|
| 用户名 | `data.viewer.name`（回退到 `data.viewer.login`） |
| 仓库列表 | `data.viewer.repositories.nodes[]` + `data.viewer.repositoriesContributedTo.nodes[]` |
| Star 总数 | 每个仓库的 `stargazers.totalCount` 累加 |
| Fork 总数 | 每个仓库的 `forkCount` 累加 |
| 语言统计 | 每个仓库的 `languages.edges[]` 中的 `size` / `node.name` / `node.color` |
| 分页游标 | `pageInfo.hasNextPage` + `pageInfo.endCursor` |

---

### 2.2 GraphQL — `contrib_years()`：获取贡献年份列表

**代码位置**：`github_stats.py:207-220`（查询定义）、`github_stats.py:465-471`（调用）

#### 请求

```
POST https://api.github.com/graphql
Authorization: Bearer ghp_xxxxxxxxxxxx
Content-Type: application/json

{
  "query": "query { viewer { contributionsCollection { contributionYears } } }"
}
```

#### 响应（200 OK）

```json
{
  "data": {
    "viewer": {
      "contributionsCollection": {
        "contributionYears": [2026, 2025, 2024, 2023, 2022, 2021]
      }
    }
  }
}
```

#### 代码提取的字段

```python
years = result["data"]["viewer"]["contributionsCollection"]["contributionYears"]
# → ["2026", "2025", "2024", ...] （List[str]）
```

---

### 2.3 GraphQL — `all_contribs(years)`：批量获取各年贡献数

**代码位置**：`github_stats.py:239-252`（查询定义）、`github_stats.py:472-482`（调用）

#### 请求

```
POST https://api.github.com/graphql
Authorization: Bearer ghp_xxxxxxxxxxxx
Content-Type: application/json

{
  "query": "query { viewer { year2026: contributionsCollection(from: \"2026-01-01T00:00:00Z\", to: \"2027-01-01T00:00:00Z\") { contributionCalendar { totalContributions } } year2025: contributionsCollection(from: \"2025-01-01T00:00:00Z\", to: \"2026-01-01T00:00:00Z\") { contributionCalendar { totalContributions } } year2024: contributionsCollection(from: \"2024-01-01T00:00:00Z\", to: \"2025-01-01T00:00:00Z\") { contributionCalendar { totalContributions } } } }"
}
```

> 使用 GraphQL 别名（alias）将多个年份的查询合并为一次请求，避免多次往返。

#### 响应（200 OK）

```json
{
  "data": {
    "viewer": {
      "year2026": {
        "contributionCalendar": {
          "totalContributions": 245
        }
      },
      "year2025": {
        "contributionCalendar": {
          "totalContributions": 1023
        }
      },
      "year2024": {
        "contributionCalendar": {
          "totalContributions": 876
        }
      }
    }
  }
}
```

#### 代码提取的字段

```python
by_year = result["data"]["viewer"].values()
# 遍历每个年份，累加 contributionCalendar.totalContributions
total = sum(year["contributionCalendar"]["totalContributions"] for year in by_year)
# → 2144
```

---

### 2.4 REST — `/repos/{owner}/{repo}/stats/contributors`：代码增删行数

**代码位置**：`github_stats.py:484-510`（调用逻辑）、`github_stats.py:85-124`（重试逻辑）

#### 请求

```
GET https://api.github.com/repos/yansheng836/project-a/stats/contributors
Authorization: token ghp_xxxxxxxxxxxx
```

> 对每个仓库逐一调用，N 个仓库 = N 次请求。

#### 响应 — 成功（200 OK）

```json
[
  {
    "author": {
      "login": "yansheng836",
      "id": 12345678,
      "avatar_url": "https://avatars.githubusercontent.com/u/12345678",
      "html_url": "https://github.com/yansheng836"
    },
    "total": 1520,
    "weeks": [
      { "w": "1609459200", "a": 350, "d": 120, "c": 5 },
      { "w": "1610064000", "a": 80,  "d": 45,  "c": 2 },
      { "w": "1610668800", "a": 0,   "d": 0,   "c": 0 }
    ]
  },
  {
    "author": {
      "login": "other-contributor",
      "id": 87654321
    },
    "total": 340,
    "weeks": [
      { "w": "1609459200", "a": 200, "d": 100, "c": 3 }
    ]
  }
]
```

| 字段 | 含义 |
|------|------|
| `author.login` | 贡献者用户名 |
| `weeks[].a` | 该周新增行数（additions） |
| `weeks[].d` | 该周删除行数（deletions） |
| `weeks[].c` | 该周提交次数（commits） |
| `weeks[].w` | 该周的 Unix 时间戳（周一） |

#### 响应 — 计算中（202 Accepted）

```
HTTP/1.1 202 Accepted
Content-Length: 0
```

GitHub 对此端点采用**懒计算**，首次请求（或数据过期时）返回空的 202 响应，表示后台正在统计。项目代码的处理逻辑（`github_stats.py:93-97`）：

```python
if r_async.status == 202:
    wait = min(2 ** (attempt + 1), 30)   # 指数退避：4, 8, 16, 30, 30, ...
    await asyncio.sleep(wait)
    continue
```

最多重试 10 次，单个仓库最坏等待：4 + 8 + 16 + 30×7 = **238 秒**。

#### 代码提取的字段

```python
for author_obj in response:                    # 遍历每个贡献者
    author = author_obj["author"]["login"]
    if author == self.username:                # 只统计当前用户
        for week in author_obj["weeks"]:
            additions += week["a"]             # 累加新增行数
            deletions  += week["d"]            # 累加删除行数
```

---

### 2.5 REST — `/repos/{owner}/{repo}/traffic/views`：页面浏览量

**代码位置**：`github_stats.py:512-528`（调用逻辑）

#### 请求

```
GET https://api.github.com/repos/yansheng836/project-a/traffic/views
Authorization: token ghp_xxxxxxxxxxxx
```

> 对每个仓库逐一调用。需要对仓库有 **push 权限**，否则返回 403。

#### 响应 — 成功（200 OK）

```json
{
  "count": 186,
  "uniques": 42,
  "views": [
    { "timestamp": "2026-06-01T00:00:00Z", "count": 15, "uniques": 8 },
    { "timestamp": "2026-06-02T00:00:00Z", "count": 22, "uniques": 12 },
    { "timestamp": "2026-06-03T00:00:00Z", "count": 18, "uniques": 10 },
    { "timestamp": "2026-06-04T00:00:00Z", "count": 30, "uniques": 15 },
    { "timestamp": "2026-06-05T00:00:00Z", "count": 25, "uniques": 14 }
  ]
}
```

| 字段 | 含义 |
|------|------|
| `count` | 近 14 天总浏览次数 |
| `uniques` | 近 14 天独立访客数 |
| `views[].timestamp` | 日期 |
| `views[].count` | 当日浏览次数 |
| `views[].uniques` | 当日独立访客数 |

#### 响应 — 无权限（403 Forbidden）

```json
{
  "message": "Must have push access to repository",
  "documentation_url": "https://docs.github.com/rest/reference/repos#get-page-views"
}
```

#### 代码提取的字段

```python
for view in response.get("views", []):
    total += view["count"]     # 累加每日浏览次数
```

---

## 3. 环境变量与密钥

### 3.1 变量总览

| 变量名 | 用途 | 是否必需 | 来源 |
|--------|------|----------|------|
| `ACCESS_TOKEN` | GitHub Personal Access Token（需 `read:user` + `repo` 权限） | 必需 | GitHub Actions Secret |
| `GITHUB_ACTOR` | GitHub 用户名 | 必需 | Actions 自动提供 |
| `EXCLUDED` | 排除的仓库列表（逗号分隔，如 `owner/repo1,owner/repo2`） | 可选 | GitHub Actions Secret |
| `EXCLUDED_LANGS` | 排除的语言列表（逗号分隔，如 `html,tex`） | 可选 | GitHub Actions Secret |
| `EXCLUDE_FORKED_REPOS` | 是否排除 fork 仓库（`true`/`false`） | 可选 | workflow 中硬编码为 `true` |

### 3.2 变量流转与影响范围

所有环境变量在 `generate_images.py` 中读取，传入 `Stats` 构造函数后影响后续 API 调用或数据处理：

```
generate_images.py 读取环境变量
        │
        ▼
Stats.__init__(exclude_repos, exclude_langs, ignore_forked_repos)
        │
        ▼
Queries.__init__(username, access_token)
        │
        ├──→ query()       使用 access_token 认证 GraphQL 请求
        ├──→ query_rest()  使用 access_token 认证 REST 请求
        └──→ lines_changed 使用 username 过滤当前用户的贡献记录
```

### 3.3 各变量影响的 API 和数据处理

#### `ACCESS_TOKEN` — 影响所有 API 请求

| 影响的 API | 影响方式 | 代码位置 |
|-----------|---------|----------|
| GraphQL `repos_overview` | `Authorization: Bearer {token}` 请求头 | `github_stats.py:42` |
| GraphQL `contrib_years` | 同上 | 同上 |
| GraphQL `all_contribs` | 同上 | 同上 |
| REST `/stats/contributors` | `Authorization: token {token}` 请求头 | `github_stats.py:82` |
| REST `/traffic/views` | 同上 | 同上 |

> Token 权限要求：`read:user`（读取用户信息和贡献数据）、`repo`（访问私有仓库统计和 traffic 数据）。

#### `GITHUB_ACTOR` — 影响所有 API 请求 + 数据过滤

| 影响的 API/逻辑 | 影响方式 | 代码位置 |
|----------------|---------|----------|
| 所有 GraphQL/REST 请求 | 作为 `Queries.username`，部分查询基于当前用户上下文 | `github_stats.py:29` |
| `lines_changed` 数据过滤 | 遍历 `/stats/contributors` 返回的贡献者列表，**只累加 `login == username` 的记录** | `github_stats.py:501-502` |

#### `EXCLUDED` — 影响 GraphQL 响应的数据过滤

| 影响的 API/逻辑 | 影响方式 | 代码位置 |
|----------------|---------|----------|
| `repos_overview` 响应处理 | 遍历返回的仓库列表时，**跳过 `nameWithOwner` 在排除集合中的仓库**。被排除的仓库不会计入 star、fork、语言统计，也不会触发后续的 REST API 调用 | `github_stats.py:351` |

示例：设置 `EXCLUDED=yansheng836/test-repo,yansheng836/old-project` 后：
- GraphQL 仍会返回这些仓库的数据（无法在查询层过滤）
- 但代码在遍历时会跳过，不计入任何统计
- 后续不会对这些仓库调用 `/stats/contributors` 和 `/traffic/views`

#### `EXCLUDED_LANGS` — 影响 GraphQL 响应的语言数据过滤

| 影响的 API/逻辑 | 影响方式 | 代码位置 |
|----------------|---------|----------|
| `repos_overview` 响应处理 | 遍历每个仓库的语言列表时，**跳过名称（不区分大小写）在排除集合中的语言**，不计入语言统计 | `github_stats.py:360` |

示例：设置 `EXCLUDED_LANGS=HTML,TeX` 后：
- 每个仓库的 GraphQL 响应中仍包含这些语言的数据
- 但代码遍历时会跳过，最终 `languages.svg` 中不会显示 HTML 和 TeX

#### `EXCLUDE_FORKED_REPOS` — 影响 GraphQL 查询的仓库范围

| 影响的 API/逻辑 | 影响方式 | 代码位置 |
|----------------|---------|----------|
| `repos_overview` 响应处理 | 为 `true` 时，**完全忽略 `repositoriesContributedTo` 返回的仓库**（即 fork 仓库和他人项目的贡献仓库），只统计自己拥有的仓库 | `github_stats.py:344` |

示例：workflow 中硬编码 `EXCLUDE_FORKED_REPOS=true`：
- GraphQL 查询仍然请求 `repositoriesContributedTo` 字段（无法动态修改查询）
- 但返回结果被代码丢弃，不计入 star/fork/语言统计
- 被忽略的仓库也不会触发 REST API 调用（节省请求次数）

### 3.4 变量对 API 调用次数的影响

以用户拥有 10 个 owned 仓库 + 5 个 contributedTo 仓库为例：

| 变量配置 | GraphQL 次数 | REST 次数 | 说明 |
|----------|-------------|-----------|------|
| 全部默认 | 3 | (10+5)×2 = 30 | 15 个仓库各调 2 个 REST 端点 |
| `EXCLUDED` 排除 3 个仓库 | 3 | 12×2 = 24 | 被排除的仓库不触发 REST 调用 |
| `EXCLUDE_FORKED_REPOS=true` | 3 | 10×2 = 20 | contributedTo 的 5 个仓库被跳过 |
| `EXCLUDED` + `EXCLUDE_FORKED_REPOS` | 3 | 7×2 = 14 | 两者叠加效果 |

---

## 4. 性能瓶颈分析

### 4.1 慢速排行

```
慢 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 快

lines_changed        views         仓库分页        贡献统计
(REST N次+重试)    (REST N次)    (GraphQL分页)   (GraphQL 2次)
```

### 4.2 `lines_changed` — 最慢（瓶颈）

- **问题**：对每个仓库调用一次 `/stats/contributors`，O(N) 次 REST 请求
- **重试逻辑**（`github_stats.py:85-124`）：HTTP 202 时最多重试 10 次，指数退避
  - 等待时间：`min(2^(attempt+1), 30)` 秒 → 4s, 8s, 16s, 30s, 30s, ...
  - 单个仓库最坏等待：约 **238 秒**
- **并发限制**：信号量限制为 10 个并发连接（`github_stats.py:32`）
- **预估耗时**：50 个仓库，假设一半触发 202 重试 → 可能达到 **数分钟**

### 4.3 `views` — 较慢

- 对每个仓库调用一次 `/traffic/views`，同样 O(N) 次 REST 请求
- 不太会触发 202 重试，但受限于并发信号量（10）
- **预估耗时**：50 个仓库约需 5-10 轮并发请求

### 4.4 仓库列表分页 — 中等

- 每页 100 个仓库，超过时需多次 GraphQL 请求
- 仓库数 < 100 时只需 1 次请求，影响较小

### 4.5 贡献统计 — 最快

- 先查年份列表（1 次 GraphQL），再批量查所有年份贡献（1 次 GraphQL）
- 共 2 次请求，固定开销

---

## 5. 其他潜在问题

### 5.1 异步回退阻塞事件循环

当 `aiohttp` 请求失败时，代码回退到同步的 `requests` 库（`github_stats.py:58, 107`）。但这些同步调用发生在 `async` 方法内部，会**阻塞事件循环**，导致其他并发任务被挂起，破坏异步优势。

### 5.2 超时配置不匹配

- `aiohttp.ClientTimeout(total=60)` 是**单次请求**的超时（`generate_images.py:123`）
- REST 202 重试逻辑的最坏等待远超 60 秒，但重试中的 `await asyncio.sleep()` 不计入请求超时
- 整个流程没有总超时限制，GitHub Actions 默认超时为 **6 小时**

### 5.3 `/traffic/views` 权限限制

该端点要求 token 对仓库有 **push 权限**。对于 contributedTo 的仓库（非 owned），如果用户没有 push 权限，请求会返回 403 或空数据。

---

## 6. 运行流程图

```
GitHub Actions (每日 00:05 UTC)
    │
    ├─ generate_images.py 启动
    │   │
    │   ├─ 读取环境变量 (ACCESS_TOKEN, GITHUB_ACTOR, EXCLUDED, ...)
    │   │
    │   ├─ 创建 aiohttp session (timeout=60s)
    │   │
    │   └─ 并发执行 generate_languages() + generate_overview()
    │       │
    │       └─ 访问 Stats 属性时触发懒加载：
    │           │
    │           ├─ get_stats() ──────── GraphQL repos_overview (分页循环)
    │           │                       → 获取 star/fork/语言/仓库列表
    │           │
    │           ├─ total_contributions ─ GraphQL contrib_years + all_contribs
    │           │                       → 获取贡献总数
    │           │
    │           ├─ lines_changed ────── REST /stats/contributors × N 个仓库
    │           │                       → 获取增删行数 (可能 202 重试)
    │           │
    │           └─ views ────────────── REST /traffic/views × N 个仓库
    │                                   → 获取页面浏览量
    │
    ├─ 写入 generated/overview.svg
    ├─ 写入 generated/languages.svg
    │
    └─ git add + commit + push
```

---

## 7. 完整数据流示例

以用户 `yansheng836` 拥有 3 个仓库为例，展示完整的请求序列：

```
请求 #1: GraphQL repos_overview (page 1)
  → 返回 3 个 owned 仓库 + 1 个 contributedTo 仓库
  → hasNextPage=false，分页结束

请求 #2: GraphQL contrib_years
  → 返回 [2026, 2025, 2024]

请求 #3: GraphQL all_contribs(["2026","2025","2024"])
  → 返回各年贡献总数：245 + 1023 + 876 = 2144

请求 #4~#7: REST /repos/{repo}/stats/contributors × 4 个仓库
  → 可能返回 202 需重试，最终返回每周增删行数
  → 累加得到总新增/删除行数

请求 #8~#11: REST /repos/{repo}/traffic/views × 4 个仓库
  → 返回近 14 天浏览量
  → 累加得到总浏览量

总请求次数：1 + 1 + 1 + 4 + 4 = 11 次（无 202 重试时）
最坏情况：1 + 1 + 1 + 4×10 + 4 = 47 次（每个仓库都触发 10 次重试）
```
