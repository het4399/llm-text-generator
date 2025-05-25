# LLM Text Generator

A modern web application that transforms any website into structured, AI-ready content with beautiful UI and advanced features.

## 🚀 Features

- **Modern UI/UX Design**: Clean, professional interface with gradient colors and smooth animations
- **Dual Output Modes**: 
  - **LLM Text (Summarized)**: AI-generated concise summaries of each page
  - **LLM Full Text**: Complete page content extraction
- **Smart Content Extraction**: Advanced algorithms to identify and extract main content
- **Download Functionality**: Export generated content as `llms.txt` files
- **Responsive Design**: Works perfectly on desktop, tablet, and mobile devices
- **Real-time Processing**: Live progress indicators and status updates
- **Enhanced Link Analysis**: Intelligent filtering and title extraction from internal links

## 🛠️ Setup and Installation

1. **Clone this repository**
   ```bash
   git clone https://github.com/creadigol/llm-text-generator.git
   cd llm-text-generator
   ```

2. **Install the required dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your OpenAI API key**
   
   Create a `.env` file in the project root:
   ```env
   OPENAI_API_KEY=your_api_key_here
   REQUEST_TIMEOUT=15
   CONCURRENT_WORKERS=5
   API_CALL_DELAY=0.5
   ```
   
   Or set as environment variable:
   ```bash
   # On macOS/Linux
   export OPENAI_API_KEY=your_api_key_here
   
   # On Windows
   set OPENAI_API_KEY=your_api_key_here
   ```

## 🚀 Running the Application

1. **Start the Flask server**
   ```bash
   python app.py
   ```

2. **Open your browser** and navigate to `http://127.0.0.1:5000`

## 📱 Usage

1. **Choose Output Type**: Select between summarized or full content extraction
2. **Enter Website URL**: Input any website URL (e.g., https://example.com)
3. **Generate Content**: Click the "Generate LLM Text" button
4. **View Results**: See the processed content in the output area
5. **Export**: Use "Copy to Clipboard" or "Download text file" to save results

## 🎨 UI Features

- **Gradient Design**: Beautiful color schemes with modern gradients
- **Interactive Elements**: Hover effects and smooth transitions
- **Processing Overlay**: Full-screen loading interface with progress tracking
- **Status Indicators**: Color-coded feedback for different states
- **Responsive Layout**: Optimized for all screen sizes

## 📁 Project Structure

```
llm-text-generator/
├── app.py                 # Main Flask application
├── templates/
│   └── index.html        # Frontend HTML template
├── static/
│   ├── css/
│   │   └── style.css     # Modern CSS styling
│   └── js/
│       └── script.js     # Frontend JavaScript
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
└── README.md             # This file
```

## ⚙️ Configuration Options

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `OPENAI_API_KEY` | None | Your OpenAI API key (required for summarization) |
| `REQUEST_TIMEOUT` | 15 | Timeout for web requests (seconds) |
| `CONCURRENT_WORKERS` | 5 | Number of concurrent processing threads |
| `API_CALL_DELAY` | 0.5 | Delay between API calls (seconds) |

## 🔧 Technical Details

- **Backend**: Flask (Python)
- **Frontend**: Vanilla JavaScript with modern CSS
- **AI Integration**: OpenAI GPT for content summarization
- **Web Scraping**: BeautifulSoup for HTML parsing
- **Concurrency**: ThreadPoolExecutor for parallel processing
- **Styling**: CSS Grid, Flexbox, and CSS Custom Properties

## 📝 Output Formats

### LLM Text (Summarized)
- Site description
- AI-generated summaries of internal pages
- Structured format optimized for LLM consumption

### LLM Full Text
- Complete page content extraction
- Unprocessed text from all internal pages
- Suitable for RAG applications or large context models

## 🛡️ Error Handling

- **Robots.txt Compliance**: Respects website scraping policies
- **Timeout Management**: Handles slow-loading websites gracefully
- **Rate Limiting**: Built-in delays to avoid overwhelming servers
- **Fallback Mechanisms**: Graceful degradation when AI services are unavailable

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

## 🙏 Acknowledgments

- OpenAI for GPT API
- Flask community for the excellent framework
- Contributors and users of this project
