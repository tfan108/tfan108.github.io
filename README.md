# 唐帆个人主页 · 维护说明

网站地址：<https://tfan108.github.io>

日常更新只需要改 `data/` 目录下的几个文本文件，保存并推送到 GitHub 后，大约 1 分钟网站自动更新。
Google Scholar 引用数和 GitHub star 数每天自动抓取，不用手动维护。

```
data/                  ← 日常只改这里
├── papers.yml         论文（新增论文就改这个）
├── venues.yml         会议/期刊表：简称、全称、CCF 等级（遇到新会议时加一条）
├── news.yml           新闻
├── members.yml        团队成员
├── cv.yml             CV 页面
├── site.yml           个人信息、导航、首页代表性工作（很少改）
├── pages/intro.md     首页个人简介
├── pages/join-us.md   招生信息（首页和团队页都会显示）
├── metrics.json       引用数 / star 数（自动生成，不要手改）
└── legacy_redirects.yml  旧网址跳转（不用管）
static/                图片、PDF 等，原样发布到网站根目录
  ├── images/members/  成员照片
  ├── images/papers/   论文缩略图（可选）
  └── files/           想放到网站上的 PDF 等
templates/  build.py  scripts/   网站程序（一般不用动）
```

---

## 一、新增论文

### 需要准备什么

| 内容 | 是否必填 | 说明 |
|---|---|---|
| 标题 `title` | 必填 | 含英文冒号时整体加英文双引号 |
| 作者 `authors` | 必填 | 按署名顺序，英文名，如 `[Zhang San, Fan Tang]` |
| 会议/期刊 `venue` | 必填 | 写简称，如 `CVPR`、`TOG`、`TVCG`，必须是 `venues.yml` 里有的 |
| 年份 `year` | 必填 | |
| 通讯作者 `corresponding` | 建议 | 名字写法须与 `authors` 中完全一致，可多个；显示 ✉ |
| 代码 `links.code` | 建议 | GitHub 地址，自动显示 GitHub 图标和 star 数 |
| 论文链接 `links.pdf` / `links.arxiv` | 建议 | 标题会链接到 PDF（没有则链接到 arXiv） |
| 共同一作 `equal` | 可选 | 显示 * |
| 小标签 `note` | 可选 | 如 `Oral`、`Highlight`、`Best Paper` |
| 其他链接 | 可选 | `project` 项目主页、`video`、`slides`、`poster`、`doi` … |
| 缩略图 `image` | 可选 | 放到 `static/images/papers/`，自动压缩 |
| BibTeX `bibtex` | 可选 | 不填会自动生成 |

**会议级别（CCF-A 等）不用在每篇论文里写**，在 `data/venues.yml` 中每个会议/期刊设置一次即可。
**引用数不用填**，会按标题自动匹配 Google Scholar。

### 写法一：逐项填写

打开 `data/papers.yml`，把下面这段粘贴到列表最上面（顺序无所谓，页面按年份和会议自动排序），改成实际内容：

```yaml
- title: "TAG-MoE: Task-Aware Gating for Unified Generative Mixture-of-Experts"
  authors: [Yu Xu, Hongbin Yan, Juan Cao, Fan Tang]
  corresponding: [Fan Tang]
  venue: CVPR
  year: 2026
  links:
    arxiv: https://arxiv.org/abs/2601.08881
    code: https://github.com/ICTMCG/TAG-MoE
```

### 写法二：粘贴 BibTeX（最省事）

从 Google Scholar / DBLP 复制 BibTeX，标题、作者、年份会自动读取，只需补 `venue` 和通讯作者：

```yaml
- venue: CVPR
  corresponding: [Fan Tang]
  links:
    code: https://github.com/ICTMCG/TAG-MoE
  bibtex: |
    @inproceedings{xu2026tagmoe,
      title={TAG-MoE: Task-Aware Gating for Unified Generative Mixture-of-Experts},
      author={Xu, Yu and Yan, Hongbin and Cao, Juan and Tang, Fan},
      booktitle={CVPR},
      year={2026}
    }
```

> 注意 `bibtex: |` 下面每一行都要比 `bibtex` 多缩进两个空格。

### 遇到新会议/期刊

在 `data/venues.yml` 加一条（放在哪个位置，就决定了同一年里它排在第几）：

```yaml
ECCV:
  name: European Conference on Computer Vision
  type: conference        # conference / journal / preprint / poster / workshop
  rank: CCF-B             # 不需要就留空
  aliases: [eccv2026]     # 可选别名
```

预印本用 `venue: arXiv`，会显示在论文页最上方的 Preprints 分组；正式录用后把 `venue` 和 `year` 改掉即可。

---

## 二、新增新闻

打开 `data/news.yml`，在最上面加：

```yaml
- date: 2026-09-25
  icon: "🎉"
  text: "Our paper **XXX** was accepted to **SIGGRAPH Asia 2026**. Congratulations to Zhang San!"
```

- `date` 可以只写到月：`2026-09`
- `text` 支持 Markdown：`**加粗**`、`*斜体*`、`[链接文字](https://...)`
- 首页显示最近 8 条（数量在 `site.yml → home.news_count` 改），全部新闻在 /news/ 页面
- 想让某条一直显示在首页最上面：加 `pin: true`

---

## 三、团队成员

1. 照片放到 `static/images/members/`（jpg/png 都行，原图即可，构建时会自动裁成正方形并压缩；竖幅照片会偏上取景保留头部）
2. 在 `data/members.yml` 中添加：

```yaml
- name: San Zhang              # 英文名，和论文作者名写法一致时会自动统计他的论文数
  name_zh: 张三
  role: phd                    # faculty / postdoc / phd / master / intern / alumni
  photo: /images/members/zhangsan.jpg
  since: 2024
  research: [Image editing, Diffusion models]
  experience:                  # 简单的学习/工作经历，每行“时间 + 两个空格 + 内容”
    - 2024–now  Ph.D. Student, ICT, CAS
    - 2020–2024 B.E., Jilin University
  links:
    github: https://github.com/zhangsan
    email: zhangsan@ict.ac.cn
```

- 学生毕业：把 `role` 改成 `alumni`，可加 `graduated: 2027` 和 `destination: 去向`，会显示在 Alumni 列表
- 分组名称和顺序在 `site.yml → team.groups` 中修改

---

## 四、其他内容

| 想改的内容 | 文件 |
|---|---|
| 首页简介 | `data/pages/intro.md` |
| 招生信息 Join Us | `data/pages/join-us.md` |
| 首页座右铭、代表性工作的图片和关联论文 | `data/site.yml → home` |
| 左侧个人信息栏、头像、导航栏 | `data/site.yml` |
| CV | `data/cv.yml` |
| 配色、字号 | `static/assets/style.css` 开头的 `:root` |

---

## 五、怎么改、怎么发布

**方式 A：直接在 GitHub 网页上改（最简单，手机也行）**
打开仓库 → 进入 `data/` → 点开要改的文件 → 右上角铅笔图标 → 修改 → Commit changes。
约 1 分钟后网站更新。可在仓库的 **Actions** 页面看进度，红色 ✗ 表示填写有误，点进去能看到具体哪一行、什么问题。

**方式 B：本地修改并预览**

```bash
pip install -r requirements.txt     # 第一次需要
python build.py --serve             # 预览：http://localhost:8000
```

Windows 可以直接双击 `preview.bat`。预览运行时，保存 `data/` 下的文件会自动重新生成并刷新浏览器。
满意后 commit 并 push 到 GitHub 即可。

---

## 六、引用数和 star 数

- 每天北京时间凌晨自动运行（`.github/workflows/deploy.yml`），抓取 Google Scholar 个人主页和各论文代码仓库的 star 数，然后重新发布网站。
- 数据保存在仓库的 `metrics` 分支（机器人只往那里提交，不会在 `master` 上产生自动提交，本地 push 不会冲突）。
- Google 偶尔会拦截 GitHub 服务器的访问。这时会保留上一次的数据，网站照常显示。
  如果经常失败，可以注册 [SerpAPI](https://serpapi.com)（免费额度每月 100 次），在仓库 **Settings → Secrets and variables → Actions** 中添加名为 `SERPAPI_KEY` 的密钥，抓取失败时会自动改用它。
- 想立刻更新：仓库 **Actions → Build & Deploy → Run workflow**。
- 每次构建的日志里会列出“Google Scholar 上有、但 `papers.yml` 里没有”的论文，方便查漏补缺。
- 个别论文标题和 Scholar 上差别较大导致匹配不到时，日志会提示；在该论文下加一行 `scholar: xxxx` 即可（`xxxx` 是 Scholar 论文详情页网址中 `citation_for_view=PdKElfwAAAAJ:` 后面的部分）。

---

## 七、填错了怎么办

构建会检查数据，出错时 Actions 显示红色 ✗，**网站保持上一个正常版本不变**。日志里的提示类似：

```
✗ papers.yml 第 31 行《A New Paper》: venue “NeurIPS2026” 不在 venues.yml 中……
✗ papers.yml 第 31 行《A New Paper》: corresponding 里的 “Fan tang” 不在 authors 中（名字写法必须完全一致）
✗ data/papers.yml 第 45 行 YAML 格式错误……常见原因：缩进不对齐；标题里有英文冒号却没加双引号……
```

按提示改好再提交即可。字段名拼错（例如 `corrsponding`）会给出警告。

---

## 首次启用（只需一次）

1. 仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**
2. 仓库 **Actions** 页面，如提示启用 workflow，点击启用；然后手动 **Run workflow** 一次
3. （可选）按第六节添加 `SERPAPI_KEY`

> 注：GitHub 会在仓库 60 天没有任何活动时暂停定时任务（会发邮件提醒），到 Actions 页面重新启用即可。
