// Main JavaScript file for OrpheusDL Web Interface

// Show loading spinner
function showLoading() {
    const spinner = `
        <div class="spinner-overlay">
            <div class="spinner-border text-primary spinner" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>
    `;
    $('body').append(spinner);
}

// Hide loading spinner
function hideLoading() {
    $('.spinner-overlay').remove();
}

// Show alert message
function showAlert(message, type = 'success') {
    const alert = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `;
    $('.container').prepend(alert);
    
    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        $('.alert').alert('close');
    }, 5000);
}

// Handle form submission errors
function handleFormError(xhr) {
    let errorMessage = 'An error occurred';
    if (xhr.responseJSON && xhr.responseJSON.error) {
        errorMessage = xhr.responseJSON.error;
    }
    showAlert(errorMessage, 'danger');
}

// Initialize tooltips
function initTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

// Initialize popovers
function initPopovers() {
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
}

// Handle module selection change
function handleModuleChange() {
    const moduleSelect = $('#module');
    const queryTypeSelect = $('#query_type');
    
    moduleSelect.on('change', function() {
        const selectedModule = $(this).val();
        // You can add module-specific logic here
        // For example, updating available query types based on the module
    });
}

// Handle search form submission
function handleSearchForm() {
    $('#searchForm').on('submit', function(e) {
        e.preventDefault();
        showLoading();
        
        $.ajax({
            url: window.location.href,
            method: 'POST',
            data: $(this).serialize(),
            success: function(response) {
                hideLoading();
                displaySearchResults(response);
            },
            error: function(xhr) {
                hideLoading();
                handleFormError(xhr);
            }
        });
    });
}

// Display search results
function displaySearchResults(results) {
    $('#searchResults').removeClass('d-none');
    const resultsList = $('#resultsList');
    resultsList.empty();
    
    results.forEach(function(item, index) {
        const resultItem = createResultItem(item, index);
        resultsList.append(resultItem);
    });
}

// Create result item element
function createResultItem(item, index) {
    const additionalDetails = [];
    if (item.explicit) additionalDetails.push('[E]');
    if (item.duration) additionalDetails.push(`[${item.duration}]`);
    if (item.year) additionalDetails.push(`[${item.year}]`);
    if (item.additional) additionalDetails.push(...item.additional.map(i => `[${i}]`));
    
    const detailsText = additionalDetails.length > 0 ? ` ${additionalDetails.join(' ')}` : '';
    const artistsText = item.artists ? ` - ${item.artists.join(', ')}` : '';
    
    return $(`
        <div class="list-group-item">
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <h5 class="mb-1">${item.name}${artistsText}</h5>
                    <small class="text-muted">${detailsText}</small>
                </div>
                <button class="btn btn-sm btn-primary download-btn" data-index="${index}">
                    <i class="fas fa-download"></i> Download
                </button>
            </div>
        </div>
    `);
}

// Handle download button click
function handleDownloadButton() {
    $(document).on('click', '.download-btn', function() {
        const index = $(this).data('index');
        // TODO: Implement download functionality
        showAlert('Download functionality coming soon!', 'info');
    });
}

// Initialize settings page
function initSettingsPage() {
    // Add any settings page specific initialization here
    $('.nav-tabs a').on('click', function (e) {
        e.preventDefault();
        $(this).tab('show');
    });
}

// Document ready handler
$(document).ready(function() {
    initTooltips();
    initPopovers();
    handleModuleChange();
    handleSearchForm();
    handleDownloadButton();
    initSettingsPage();
}); 