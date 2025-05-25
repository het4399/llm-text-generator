# LLM Text Generator

A simple web application that generates LLM text from a website URL.

## Setup and Installation

1. Clone this repository
2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set up your OpenAI API key as an environment variable:
   ```
   # On macOS/Linux
   export OPENAI_API_KEY=your_api_key_here
   
   # On Windows
   set OPENAI_API_KEY=your_api_key_here
   ```
   
   Alternatively, you can create a `.env` file in the project root with:
   ```
   OPENAI_API_KEY=your_api_key_here
   MAX_LINKS_TO_PROCESS=10
   ```

## Running the Application

1. Start the Flask server:
   ```
   python app.py
   ```
2. Open your browser and navigate to `http://127.0.0.1:5000`

## Usage

1. Enter a website URL in the input field
2. Click the "Generate LLM Text" button
3. Wait for the processing to complete (this may take some time as it processes each link)
4. View the generated output in the text area, including:
   - Site description
   - Summarized content of internal links

## Project Structure

- `app.py`: Main Flask application
- `templates/index.html`: Frontend HTML template
- `static/css/style.css`: CSS styling
- `static/js/script.js`: Frontend JavaScript

## Notes

- If no OpenAI API key is provided, the application will use a fallback method to generate summaries based on page metadata and content.
- The maximum number of links processed can be controlled with the `MAX_LINKS_TO_PROCESS` environment variable (default: 10). 