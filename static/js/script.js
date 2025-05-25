document.addEventListener('DOMContentLoaded', () => {
    const websiteUrlInput = document.getElementById('websiteUrl');
    const generateBtn = document.getElementById('generateBtn');
    const outputText = document.getElementById('outputText');
    const statusMessage = document.getElementById('statusMessage');
    const copyBtn = document.getElementById('copyBtn');
    const copyMessage = document.getElementById('copyMessage');
    const processingOverlay = document.getElementById('processingOverlay');
    const processingDetail = document.getElementById('processingDetail');
    const progressBar = document.getElementById('progressBar');

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
            statusMessage.style.color = 'gray';
            
            // Hide copy button and message while processing
            copyBtn.style.display = 'none';
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
        
        // Show error message
        statusMessage.textContent = `Error: ${message}`;
        statusMessage.style.color = 'red';
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
        
        // Set UI to processing state
        setProcessingState(true, 'Fetching website content...');

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
                body: JSON.stringify({ url: url })
            });

            // Complete the progress animation
            completeProgressAnimation();
            
            // Add a small delay before hiding the overlay for smoother transition
            setTimeout(() => {
                // Reset UI processing state
                setProcessingState(false);
                
                if (!response.ok) {
                    try {
                        const errorData = response.json();
                        throw new Error(errorData.error || `HTTP error: ${response.status}`);
                    } catch {
                        throw new Error(`HTTP error: ${response.status}`);
                    }
                }
            }, 500);

            const data = await response.json();
            
            // Display llms.txt content in output area
            outputText.value = data.llms_text;
            
            // Update status message
            statusMessage.textContent = 'Done!';
            statusMessage.style.color = 'green';
            
            // Show copy button
            copyBtn.style.display = 'inline-block';
            
            console.log('Response from server:', data);
            
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