document.addEventListener('DOMContentLoaded', () => {
    const websiteUrlInput = document.getElementById('websiteUrl');
    const generateBtn = document.getElementById('generateBtn');
    const outputText = document.getElementById('outputText');
    const statusMessage = document.getElementById('statusMessage');
    const copyBtn = document.getElementById('copyBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const clearBtn = document.getElementById('clearBtn');
    const copyMessage = document.getElementById('copyMessage');
    const processingOverlay = document.getElementById('processingOverlay');
    const processingDetail = document.getElementById('processingDetail');
    const progressBar = document.getElementById('progressBar');
    const llmsTxtRadio = document.getElementById('llmsTxt');
    const llmsFullTxtRadio = document.getElementById('llmsFullTxt');
    const llmsBothRadio = document.getElementById('llmsBoth');

    // Function to validate URL
    function isValidUrl(string) {
        try {
            // Use the URL constructor for validation
            const url = new URL(string);
            // Check if protocol is http or https
            return url.protocol === 'http:' || url.protocol === 'https:';
        } catch (_) {
            return false;
        }
    }
    
    // Function to update processing state and UI
    function setProcessingState(isProcessing, detail = null) {
        if (isProcessing) {
            // Disable button and change text
            generateBtn.disabled = true;
            generateBtn.textContent = 'Processing...';
            generateBtn.classList.add('processing');
            
            // Clear previous output
            outputText.value = '';
            
            // Show processing message
            statusMessage.textContent = 'Processing website content...';
            statusMessage.className = 'status-info';
            
            // Hide copy and download buttons and message while processing
            copyBtn.style.display = 'none';
            downloadBtn.style.display = 'none';
            copyMessage.style.display = 'none';
            
            // Show processing overlay with animation
            processingOverlay.classList.add('active');
            
            // Update detail text if provided
            if (detail) {
                processingDetail.textContent = detail;
            } else {
                processingDetail.textContent = 'This may take a few moments';
            }
            
            // Start progress animation
            startProgressAnimation();
        } else {
            // Reset button state
            generateBtn.disabled = false;
            generateBtn.textContent = 'Generate LLM Text';
            generateBtn.classList.remove('processing');
            
            // Hide processing overlay
            processingOverlay.classList.remove('active');
            
            // Reset progress bar
            progressBar.style.width = '0%';
        }
    }
    
    // Function to animate the progress bar
    function startProgressAnimation() {
        // Reset progress
        progressBar.style.width = '0%';
        
        // Animate to 90% over 20 seconds (simulating progress)
        // The remaining 10% will be filled when the response is received
        let width = 0;
        const maxWidth = 90;
        const duration = 20000; // 20 seconds
        const interval = 200; // Update every 200ms
        const increment = (maxWidth * interval) / duration;
        
        const animation = setInterval(() => {
            if (width >= maxWidth) {
                clearInterval(animation);
            } else {
                width += increment;
                progressBar.style.width = `${width}%`;
            }
        }, interval);
        
        // Store the interval ID to clear it later if needed
        window.progressAnimation = animation;
    }
    
    // Function to complete the progress animation
    function completeProgressAnimation() {
        // Clear any existing animation
        if (window.progressAnimation) {
            clearInterval(window.progressAnimation);
        }
        
        // Animate to 100%
        progressBar.style.width = '100%';
    }
    
    // Function to display error message
    function showError(message) {
        // Reset processing state first
        setProcessingState(false);
        
        // Show error message with modern styling
        statusMessage.textContent = `Error: ${message}`;
        statusMessage.className = 'status-error';
        outputText.value = `An error occurred: ${message}\n\nPlease try again with a different URL or check your API key configuration.`;
    }

    generateBtn.addEventListener('click', async () => {
        const url = websiteUrlInput.value.trim();
        
        // Client-side URL validation
        if (!url) {
            showError('Please enter a website URL');
            return;
        }
        
        if (!isValidUrl(url)) {
            showError('Invalid URL format. URL must start with http:// or https://');
            return;
        }
        
        const selectedOutputType = document.querySelector('input[name="outputType"]:checked').value;
        
        // Set UI to processing state
        setProcessingState(true, 'Fetching and processing website content...');

        try {
            // Update processing detail after a delay to simulate progress
            setTimeout(() => {
                processingDetail.textContent = 'Analyzing website structure...';
            }, 3000);
            
            setTimeout(() => {
                processingDetail.textContent = 'Extracting internal links...';
            }, 6000);
            
            setTimeout(() => {
                processingDetail.textContent = 'Generating summaries (this may take a while)...';
            }, 9000);

            // Send request to backend
            const response = await fetch('/generate_llm_text', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    websiteUrl: url,
                    outputType: selectedOutputType
                })
            });

            if (response.ok) {
                const result = await response.json();
                completeProgressAnimation();
                setProcessingState(false);

                if (result.llms_text && result.llms_full_text) {
                    // Both outputs available
                    const combinedOutput = `=== SUMMARIZED CONTENT ===\n\n${result.llms_text}\n\n=== FULL TEXT CONTENT ===\n\n${result.llms_full_text}`;
                    outputText.value = combinedOutput;
                    statusMessage.textContent = 'Both LLM Text and Full Text generated successfully!';
                    statusMessage.className = 'status-success';
                } else if (result.llms_text) {
                    outputText.value = result.llms_text;
                    statusMessage.textContent = 'LLM Text generated successfully!';
                    statusMessage.className = 'status-success';
                } else if (result.llms_full_text) {
                    outputText.value = result.llms_full_text;
                    statusMessage.textContent = 'LLM Full Text generated successfully! (Note: This content can be very large and may require specific LLM handling like RAG or a large context window.)';
                    statusMessage.className = 'status-success';
                } else {
                    showError('Unexpected response format from server.');
                }
                copyBtn.style.display = 'inline-block'; // Show copy button after success
                downloadBtn.style.display = 'inline-block'; // Show download button after success
            } else {
                const errorData = await response.json();
                showError(errorData.error || 'An unknown error occurred.');
            }
            
        } catch (error) {
            // Reset UI processing state and show error
            console.error('Error:', error);
            showError(error.message);
        }
    });
    
    // Implement copy to clipboard functionality
    copyBtn.addEventListener('click', () => {
        if (!outputText.value) {
            return;
        }
        
        // Copy text to clipboard
        outputText.select();
        outputText.setSelectionRange(0, 99999); // For mobile devices
        
        try {
            // Use the modern clipboard API if available
            if (navigator.clipboard) {
                navigator.clipboard.writeText(outputText.value)
                    .then(() => showCopySuccess())
                    .catch(err => {
                        console.error('Failed to copy: ', err);
                        // Fallback to older method on error
                        document.execCommand('copy');
                        showCopySuccess();
                    });
            } else {
                // Fallback for older browsers
                document.execCommand('copy');
                showCopySuccess();
            }
        } catch (err) {
            console.error('Copy error:', err);
        }
    });
    
    // Implement download text file functionality
    downloadBtn.addEventListener('click', () => {
        if (!outputText.value) {
            return;
        }
        
        // Get the selected output type to determine filename
        const selectedOutputType = document.querySelector('input[name="outputType"]:checked').value;
        
        // Set filename based on output type
        let filename = 'llms.txt'; // default
        if (selectedOutputType === 'llms_full_txt') {
            filename = 'llms-full.txt';
        } else if (selectedOutputType === 'llms_both') {
            filename = 'llms-both.txt';
        }
        
        // Create a blob with the text content
        const blob = new Blob([outputText.value], { type: 'text/plain' });
        
        // Create a temporary URL for the blob
        const url = window.URL.createObjectURL(blob);
        
        // Create a temporary anchor element to trigger download
        const downloadLink = document.createElement('a');
        downloadLink.href = url;
        downloadLink.download = filename; // Set the dynamic filename
        
        // Append to body, click, and remove
        document.body.appendChild(downloadLink);
        downloadLink.click();
        document.body.removeChild(downloadLink);
        
        // Clean up the URL object
        window.URL.revokeObjectURL(url);
    });
    
    // Implement clear functionality
    clearBtn.addEventListener('click', () => {
        // Clear the URL input
        websiteUrlInput.value = '';
        
        // Clear the output text
        outputText.value = '';
        
        // Clear status message
        statusMessage.textContent = '';
        statusMessage.className = '';
        
        // Hide copy and download buttons
        copyBtn.style.display = 'none';
        downloadBtn.style.display = 'none';
        copyMessage.style.display = 'none';
        
        // Reset to default output type (summarized)
        llmsTxtRadio.checked = true;
        llmsFullTxtRadio.checked = false;
        llmsBothRadio.checked = false;
        
        // Focus back to the URL input for better UX
        websiteUrlInput.focus();
    });
    
    function showCopySuccess() {
        // Show copy success message
        copyMessage.style.display = 'inline';
        copyMessage.style.opacity = 1;
        
        // Reset animation by removing and re-adding the element
        copyMessage.style.animation = 'none';
        void copyMessage.offsetWidth; // Trigger reflow
        copyMessage.style.animation = 'fadeOut 2s forwards';
        copyMessage.style.animationDelay = '1s';
        
        // Hide after animation completes
        setTimeout(() => {
            copyMessage.style.display = 'none';
        }, 3000);
    }
}); 