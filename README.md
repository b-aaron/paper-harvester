# Paper Harvester / 论文文献采集器

Paper Harvester is a Python tool for harvesting real academic papers from business and management journals, exporting structured outputs, and syncing to Zotero.

Paper Harvester 是一个 Python 文献采集工具，可从商科与管理学期刊检索真实论文，导出结构化结果，并同步到 Zotero。

Paper Harverster also can be used as a skill for Agent, triggerd by lieterature searching and reivew tasks, which help prevent LLM inventing literatures.

Paper Harvester 也可作为Agent的Skill用于文献检索、综述撰写等任务，可有效降低AI幻觉编造参考文献的概率，并提高参考文献质量。

---

## Features / 功能特点

- **Comprehensive journal coverage / 期刊覆盖全面**  
  Pre-configured with UTD24, FT50, ABS4, plus custom journal lists from JSON config files.  
  内置 UTD24、FT50、ABS4，并支持通过 JSON 配置自定义期刊列表。

- **Flexible time ranges / 时间范围灵活**  
  Latest issue, last N months/years, custom date range, or all available records.  
  支持“最新一期、近 N 月/年、自定义日期区间、全部可用记录”等模式。

- **Rich metadata / 元数据丰富**  
  Retrieves title, authors, journal, year, volume/issue, pages, DOI, abstract, keywords, publisher, URL.  
  可获取题名、作者、期刊、年份、卷期、页码、DOI、摘要、关键词、出版社、URL。

- **Grounded outputs for writing / 防幻觉写作输出**  
  Generates verified reference artifacts (`json` + `md`) and citation files in APA / GB/T 7714 / IEEE formats.  
  生成可核验的参考文献产物（`json` + `md`）以及 APA / GB/T 7714 / IEEE 引用格式文件。

- **PDF download cascade / PDF 下载级联**  
  OA sources first (Unpaywall), then fallback strategies.  
  优先开放获取来源（Unpaywall），再走后备策略。

- **Zotero integration / Zotero 集成**  
  Saves items to personal/group library and can attach downloaded PDFs.  
  可将条目写入个人/群组 Zotero 文库，并可附加已下载 PDF。

- **Interactive + headless workflows / 交互式 + 非交互式流程**  
  Use menu CLI (`main.py`) or automation-friendly script (`grounded_harvest.py`).  
  可用菜单 CLI（`main.py`）或自动化脚本（`grounded_harvest.py`）。

---

## Quick Start / 快速开始

### 1) Install dependencies / 安装依赖

```bash
pip install -r requirements.txt
```

### 2) Interactive mode / 交互模式

```bash
python main.py
```

Main menu / 主菜单:

```text
========== MAIN MENU ==========
  1. Scrape articles
  2. Manage journal list
  3. Settings
  4. Exit
```

### 3) Headless grounded mode / 非交互防幻觉模式

```bash
python grounded_harvest.py \
  --preset marketing_comprehensive \
  --mode last_n_months \
  --n 12 \
  --max-results 120 \
  --require-doi \
  --citation-formats apa,gbt,ieee \
  --zotero \
  --zotero-collection "LitReview-Seed" \
  --save-path "D:\Research\paper_harvest"
```

See all options / 查看全部参数:

```bash
python grounded_harvest.py --help
```

### 4) Generated outputs / 生成文件

- `verified_references_*.json`  
  Machine-readable verified references.  
  机器可读的可核验参考文献。

- `verified_references_*.md`  
  Human-readable verified reference list for drafting.  
  适合写作场景的人类可读参考文献清单。

- `verified_references_apa_*.txt`  
  APA citation lines.  
  APA 格式参考文献列表。

- `verified_references_gbt7714_*.txt`  
  GB/T 7714 citation lines.  
  GB/T 7714 格式参考文献列表。

- `verified_references_ieee_*.txt`  
  IEEE citation lines.  
  IEEE 格式参考文献列表。

- Optional: Excel and PDFs / 可选：Excel 与 PDF 文件。

---

## Copilot Skill: Grounded Writing + Zotero / Copilot Skill：防幻觉写作 + Zotero

This repository supports a skill-driven workflow for research proposal and literature review writing.

本仓库支持用于研究计划与文献综述写作的 Skill 工作流。

### What the skill enforces / Skill 强制规则

1. Never invent papers/DOIs/authors/venues/years.  
   不得编造论文、DOI、作者、刊名、年份。

2. Harvest first, write later.  
   先检索后写作。

3. Prefer DOI-backed references (`--require-doi`).  
   优先使用带 DOI 的文献（`--require-doi`）。

4. If evidence is missing, explicitly state insufficient evidence.  
   若证据不足，必须明确标注“证据不足”。

5. Every citation must map to generated verified artifacts.  
   每条引用都必须可追溯到已生成的 verified 文件。

### Skill usage workflow / Skill 使用流程

1. Run `grounded_harvest.py` to collect verified references and sync Zotero (optional).  
   运行 `grounded_harvest.py` 获取可核验文献，并可选同步 Zotero。

2. Use only generated outputs for citations (`json`/`md`/citation txt).  
   仅使用输出文件（`json`/`md`/引用格式 txt）中的文献进行写作引用。

3. Draft proposal/review with explicit evidence links (DOI/URL).  
   在 proposal/review 中为关键论断附 DOI/URL 证据链接。

### Install this skill with git / 通过 git 安装该 Skill

This repository now includes a sanitized `SKILL.md` at the repository root (no local machine paths).

本仓库已在根目录提供脱敏后的 `SKILL.md`（不包含任何本地机器路径信息）。

Clone directly into your skills folder:

直接克隆到你的 skills 目录：

**Windows (PowerShell):**

```powershell
git clone --depth 1 https://github.com/b-aaron/paper-harvester.git "$HOME\.agents\skills\paper-harvester-grounded-zotero"
```

**macOS / Linux:**

```bash
git clone --depth 1 https://github.com/b-aaron/paper-harvester.git ~/.agents/skills/paper-harvester-grounded-zotero
```

If you already cloned before, update skill content with:

如果你之前已经克隆过，可用以下命令更新 Skill：

```powershell
git -C "$HOME\.agents\skills\paper-harvester-grounded-zotero" pull
```

```bash
git -C ~/.agents/skills/paper-harvester-grounded-zotero pull
```

---

## Project Structure / 项目结构

```text
paper-harvester/
├── main.py                         # Interactive entry / 交互入口
├── grounded_harvest.py             # Headless grounded workflow / 非交互防幻觉流程
├── requirements.txt                # Python dependencies / 依赖
├── config/
│   ├── journals.json               # Journal metadata / 期刊元数据
│   └── presets.json                # Preset journal groups / 预设期刊组
└── harvester/
    ├── cli.py                      # Interactive CLI / 交互式 CLI
    ├── config_manager.py           # Config & settings / 配置与设置
    ├── downloader.py               # PDF downloader / PDF 下载
    ├── exporter.py                 # Excel export / Excel 导出
    ├── zotero_client.py            # Zotero API integration / Zotero API 集成
    └── scrapers/
        ├── base_scraper.py
        └── crossref_scraper.py
```

---

## Configuration / 配置说明

### Journal database (`config/journals.json`) / 期刊数据库

| Field | Description (EN) | 说明（中文） |
|---|---|---|
| `id` | Short journal key | 期刊短 ID |
| `name` | Full journal name | 期刊全称 |
| `issn_print` / `issn_electronic` | ISSN used for CrossRef queries | 用于 CrossRef 查询的 ISSN |
| `publisher` | Publisher name | 出版社 |
| `website` | Journal website | 期刊主页 |
| `lists` | Membership tags (`utd24`, `ft50`, `abs4`, etc.) | 列表标签（如 `utd24`、`ft50`、`abs4`） |
| `field` | Research field | 学科领域 |

### Presets (`config/presets.json`) / 预设期刊组

Built-in examples include: `utd24`, `ft50`, `abs4`, `marketing_comprehensive`, `finance`, `accounting`, `management`.

内置示例包括：`utd24`、`ft50`、`abs4`、`marketing_comprehensive`、`finance`、`accounting`、`management`。

### User settings (`~/.paper_harvester_settings.json`) / 用户设置

- `save_path`: output directory / 输出目录  
- `unpaywall_email`: polite-pool email / Unpaywall 邮箱  
- `zotero_library_id`, `zotero_api_key`, `zotero_library_type`: Zotero credentials / Zotero 凭据  
- `institutional_org`, `institutional_username`, `institutional_password`: institutional login / 机构登录信息  
- `google_scholar_fallback`: enable fallback / 是否启用 Scholar 回退

---

## PDF Download / PDF 下载

PDF retrieval priority:

PDF 下载优先级：

1. **Unpaywall OA links** (legal open-access first).  
   **Unpaywall 开放获取链接**（优先合法开放版本）。

2. **Institutional access fallback** (if credentials are configured).  
   **机构访问回退**（若已配置机构账号）。

3. **Google Scholar fallback** as a final attempt.  
   **Google Scholar 回退**（最后尝试）。

If no PDF is found, metadata is still exported and can still be synced to Zotero.

若未找到 PDF，元数据仍会导出，并可继续同步到 Zotero。

---

## Zotero Integration / Zotero 集成

1. Create an API key at <https://www.zotero.org/settings/keys> with write permission.  
   在 <https://www.zotero.org/settings/keys> 创建具有写权限的 API Key。

2. Get your numeric library ID from the same page.  
   在同一页面获取数字型 library ID。

3. Configure settings in app menu or pass CLI flags to `grounded_harvest.py`.  
   可在交互菜单中配置，或通过 `grounded_harvest.py` 参数传入。

---

## Extending / 扩展开发

- Add a journal: edit `config/journals.json` or use menu options.  
  新增期刊：编辑 `config/journals.json` 或使用菜单。

- Add a scraper: subclass `harvester.scrapers.base_scraper.BaseScraper`.  
  新增抓取器：继承 `harvester.scrapers.base_scraper.BaseScraper`。

- Add a preset: update `config/presets.json`.  
  新增预设：更新 `config/presets.json`。

- Add a custom list tag in journals and map it in presets.  
  在期刊配置中新增自定义列表标签，并在 preset 中完成映射。

---

## License / 许可证

MIT
