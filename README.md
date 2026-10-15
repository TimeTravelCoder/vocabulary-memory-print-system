# 单词记忆打印系统 (Vocabulary Memory Print System)

A professional, local-first A4 vocabulary printing and scientific memory review workstation. Engineered with millimetric A4 page constraints (297mm zero overflow), 8 card layout architectures, full phonetic and bilingual dictionary display, first-letter/definition cloze testing, multi-volume automatic split packaging, and direct headless PDF generation.

专为 A4 纸排版深度优化的科学单词抄写本与艾宾浩斯复习系统，内置 950+ 本覆盖全学段的中英双解词库。

---

## 核心特性 (Core Features)

### 1. 8 款卡片排版设计风格 (8 Card Layout Architectures)
系统内置 8 款满足不同学习阶段与审美偏好的排版风格：
- **学术精装风 (Academic Formal)**: 左侧主题色竖条、灰底顶栏分区、双英释整句抄写格，适合考研与深度精读。
- **极简手账风 (Minimalist Journal)**: 无外线框、轻量虚线分行、节省打印机墨水，适合活页打孔与日常自测。
- **黄金双栏风 (Golden Two-Column Split)**: 左栏 42% 释义记忆区、右栏 58% 抄写练习区，便于左右对照与纸笔遮挡。
- **经典线框风 (Classic Boxed)**: 模块化线框包裹、顶部中英释义横栏、底部多维练习格，适合字帖练习。
- **现代词典风 (Modern Lexicon)**: 仿牛津/柯林斯词典条目、音标圆角外框、英汉层次化词条箱，适合托福雅思大词汇量突破。
- **对折默写风 (Foldable Flashcard)**: 纸张中轴设立纵向对折虚线，左半页默写练习、右半页答案核对，打印后沿线对折即成便携抽测卡。
- **康奈尔网格风 (Cornell Matrix)**: 结构化笔记矩阵，左上核心词、右上释义栏、底部整宽方格抄写网格，适合笔记整理。
- **高效备考风 (Compact Sprint)**: 紧凑横向通栏单行排布、下方 5 格超宽单词连写，适合 GRE 与考前极速刷词（单页可容纳 12~16 词）。

### 2. A4 物理排版零溢出 (Strict A4 Physical Boundary)
- **绝对零溢出设计**: 严格适配国际标准 A4 尺寸 (210mm x 297mm)，每页支持 4 ~ 16 词自适应高度缩放，彻底消除打印跨页或截断。
- **4 款纸张色彩主题**: 经典商务蓝、清新护眼绿、极简素墨黑、复古牛津棕。
- **3 种装订留白模式**: 居中平衡 (标准 12mm 边距)、左侧装订 (左侧 +8mm 留白，便于活页打孔)、顶部装订 (顶部 +6mm 留白，便于上翻夹)。
- **四线三格字帖规范**: 支持开启英式四线三格辅助线，规范书写字母上下基准线。

### 3. 科学记忆与自测默写 (Scientific Memory & Cloze Testing)
- **艾宾浩斯复习打卡**: 遵循 1天、2天、4天、7天、15天 艾宾浩斯遗忘曲线周期，自动生成打卡记录胶囊。
- **智能挖空默写模式**:
  - 首字母提示默写: 自动将单词转化为首字母加下划线提示（如 `look up` 转为 `l___ u_`，`well-known` 转为 `w___-k____`）。
  - 释义遮挡默写: 智能隐去中文翻译或英文释义。
  - 单词全拼盲填: 仅保留释义与音标，检验拼写掌握程度。
- **生词洗牌与过滤**: 支持随机打乱词序（带防刷新乱序缓存）、字母升序排列，以及过滤简单词（长度 >= 5 个字母）。

### 4. 高性能导出与防卡死下载 (Direct Export & Split Volumes)
- **直连无头浏览器导出**: 调用本地 Edge / Chrome 无头内核后台渲染，一键直下矢量 PDF，大词书导出无需打开浏览器预览对话框，杜绝卡死。
- **智能分卷与 ZIP 打包**: 超大词库（数千生词）支持自动按分卷（如每 50 页 / 500 词一卷）打包下载，附带独立分卷封面与专属页码。
- **单文件离线 HTML 导出**: 导出包含完整样式与数据的单文件 HTML，可在手机、平板浏览器中随时离线查看并使用系统打印。

### 5. 950+ 本内置中英双解词库 (950+ Built-in Dictionaries)
项目配套完整的分类词库体系（收录于 `中英合并释义_JSON` 目录），包含 957 本 JSON 词典：
- **小学与初高中**: 人教版、译林版、外研版、中考高频词、高考必背大纲词。
- **大学公共英语**: 大学英语四级 (CET-4)、六级 (CET-6)、英语专四 (TEM-4)、专八 (TEM-8)。
- **研究生考试**: 考研英语一、考研英语二、考研核心高频词表。
- **出国留学考试**: 雅思 (IELTS)、托福 (TOEFL)、GRE、GMAT、SAT。
- **行业与专业英语**: 商务英语 (BEC)、计算机英语、金融英语、医学英语等。

---

## 目录结构 (Repository Structure)

```text
vocabulary-memory-print-system/
├── 启动系统.bat               # Windows 一键启动脚本
├── README.md                  # 项目说明文档
├── .gitignore                 # Git 忽略配置
├── 单词打印系统/
│   ├── index.html             # 前端工作台核心（单文件应用，包含全套 CSS 与逻辑）
│   ├── server.py              # 本地轻量多线程 HTTP 服务器与无头 PDF 转换桥梁
│   ├── catalog.json           # 950+ 词书分类索引元数据
│   ├── catalog.js             # 离线环境本地化目录索引
│   └── 启动系统.bat           # 子目录快捷启动器
└── 中英合并释义_JSON/         # 957 本分类标准化词库（JSON 格式）
    ├── 1.全国教材版本中小学同步/
    ├── 1.中考/
    ├── 2.高考/
    ├── 3.大学英语/
    ├── 3.四级/
    ├── 3.专四/
    ├── 4.六级/
    ├── 4.专八/
    ├── 5.考研/
    ├── 6.雅思/
    ├── 6.托福/
    ├── 7.出国高阶/
    ├── 8.新概念英语/
    └── 9.其他/
```

---

## 快速上手 (Quick Start)

### 环境要求
- **操作系统**: Windows 10/11, macOS, Linux
- **Python**: Python 3.8 或更高版本（无需安装任何第三方 pip 库，全部基于标准库）
- **浏览器**: Microsoft Edge 或 Google Chrome（系统自动调用其无头内核生成 PDF）

### 运行方式

#### 方式一：Windows 双击启动（推荐）
直接双击项目根目录下的 `启动系统.bat`，控制台将自动启动服务并打开默认浏览器访问系统。

#### 方式二：命令行启动
```bash
# 1. 克隆代码仓库
git clone https://github.com/TimeTravelCoder/vocabulary-memory-print-system.git
cd vocabulary-memory-print-system

# 2. 启动服务
python 单词打印系统/server.py
```
终端输出如下提示后，在浏览器中打开 `http://127.0.0.1:8899/index.html` 即可使用：
```text
============================================================
  [OK] 单词打印记忆本系统已成功启动！
  服务网址: http://127.0.0.1:8899/index.html
  （浏览器已自动打开，若未打开请手动复制上方网址打开）
============================================================
```

---

## 自定义词书格式 (Custom JSON Format)

如需导入自己的生词本，可点击界面左上角 **打开本地 JSON 文件**。数据格式为标准 JSON 数组，示例如下：

```json
[
  {
    "单词": "academic",
    "音标": "美: [ˌækəˈdemɪk] 英: [ˌækəˈdemɪk]",
    "释义(中)": "n. 大学生，学者; adj. 学术的，理论的",
    "释义(英)": "(1) a. associated with academia or an academy (2) s. hypothetical or theoretical"
  }
]
```

---

## 技术架构 (Architecture)

- **前端架构**: 原生 HTML5 / CSS3 (CSS Variables + Print Paged Media) / ES6+。零外部框架，毫秒级响应，渲染流畅。
- **后端架构**: Python 内置 `http.server.ThreadingHTTPServer`，提供高并发局部静态资源访问与安全路径校验（防御目录遍历）。
- **PDF 引擎**: 无需额外安装大型依赖，直接通过 `subprocess` 调用本机 Chromium 内核 CLI (`--headless --print-to-pdf`) 快速生成专业矢量打印件。

---

## 开源协议 (License)

本项目采用 [MIT License](LICENSE) 开源协议，欢迎学习、自用或基于此构建更多单词学习辅助工具。
