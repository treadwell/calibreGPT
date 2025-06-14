# CalibreGPT

A Calibre plugin that enhances your ebook library with GPT-powered search and analysis capabilities.

## Features

- **Semantic Search**: Search your Calibre library using natural language queries
- **Context-Based Search**: Find books similar to your selected books
- **GPT Integration**: Interact with your library using GPT-powered queries
- **Book Indexing**: Track which books have been indexed for search
- **Full-Text Search**: Search through the actual content of your books

## Requirements

- Calibre ebook management software
- Python 3.x
- OpenAI API token
- PyQt5

## Installation

1. Download the latest release from the releases page
2. Open Calibre
3. Go to Preferences → Plugins → Load plugin from file
4. Select the downloaded plugin file
5. Restart Calibre

## Configuration

1. Open Calibre
2. Go to Preferences → Plugins → CalibreGPT
3. Enter your OpenAI API token
4. (Optional) Enable debug mode for troubleshooting

## Usage

### Basic Search
1. Select the books you want to search from
2. Click the CalibreGPT icon in the toolbar
3. Enter your search query
4. Results will be marked in your library

### Context-Based Search
1. Select one or more books from your library
2. Click the CalibreGPT icon
3. Choose "Search Similar" to find books with similar content

### GPT Interaction
1. Click the CalibreGPT icon
2. Choose "GPT Query"
3. Enter your question or prompt
4. View the response in the dialog

## Development

The project consists of several key components:
- `main.py`: Main plugin interface and UI
- `engine.py`: Core search and GPT integration logic
- `test.sh`: Testing script
- `iterate.sh`: Development watch script for automatic testing

## License

[Add your license information here]

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 