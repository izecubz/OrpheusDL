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
function showAlert(type, message) {
    const alertHtml = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    $('.card').first().before(alertHtml);
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
    showAlert('danger', errorMessage);
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
        showAlert('info', 'Download functionality coming soon!');
    });
}

// Initialize settings page
function initSettingsPage() {
    // Add any settings page specific initialization here
    $('.nav-tabs a').on('click', function (e) {
        e.preventDefault();
        $(this).tab('show');
    });

    // Handle settings form submission
    $('#saveSettings').on('click', function() {
        const formData = {};
        
        // Process all form inputs
        $('#settingsForm input, #settingsForm select').each(function() {
            const name = $(this).attr('name');
            if (!name) return;
            
            const parts = name.split('.');
            let current = formData;
            
            // Build the nested structure
            for (let i = 0; i < parts.length - 1; i++) {
                if (!current[parts[i]]) {
                    current[parts[i]] = {};
                }
                current = current[parts[i]];
            }
            
            // Handle different input types
            if ($(this).attr('type') === 'checkbox') {
                current[parts[parts.length - 1]] = $(this).prop('checked');
            } else if ($(this).attr('type') === 'number') {
                current[parts[parts.length - 1]] = parseInt($(this).val(), 10);
            } else {
                current[parts[parts.length - 1]] = $(this).val();
            }
        });

        // Send settings to server
        $.ajax({
            url: '/api/settings',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(formData),
            success: function(response) {
                if (response.success) {
                    showAlert('success', 'Settings saved successfully');
                    $('#restartModule').prop('disabled', false);
                } else {
                    showAlert('danger', 'Error saving settings: ' + response.error);
                }
            },
            error: function(xhr) {
                showAlert('danger', 'Error saving settings: ' + xhr.responseText);
            }
        });
    });

    // Handle restart module button
    $('#restartModule').on('click', function() {
        $('#restartModal').modal('show');
    });

    // Handle restart confirmation
    $('#confirmRestart').on('click', function() {
        $.ajax({
            url: '/api/restart',
            method: 'POST',
            success: function(response) {
                if (response.success) {
                    showAlert('success', 'Module restarted successfully');
                    $('#restartModule').prop('disabled', true);
                    setTimeout(() => {
                        window.location.reload();
                    }, 2000);
                } else {
                    showAlert('danger', 'Error restarting module: ' + response.error);
                }
            },
            error: function(xhr) {
                showAlert('danger', 'Error restarting module: ' + xhr.responseText);
            }
        });
        $('#restartModal').modal('hide');
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