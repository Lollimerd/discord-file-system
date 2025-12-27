// Utils
const formatSize = (bytes) => {
    if (!bytes) return 'Unknown';
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

const formatDate = (dateStr) => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

// UI Interactions
document.addEventListener('DOMContentLoaded', () => {
    // Initial Animations
    const timeline = anime.timeline({ easing: 'easeOutExpo' });
    timeline
        .add({ targets: '#header', opacity: [0, 1], translateY: [-20, 0], duration: 800 })
        .add({ targets: '#upload-card', opacity: [0, 1], translateX: [-20, 0], duration: 800 }, '-=600')
        .add({ targets: '#explorer-panel', opacity: [0, 1], translateX: [20, 0], duration: 800 }, '-=700')
        .add({ targets: '#download-card', opacity: [0, 1], translateY: [20, 0], duration: 800 }, '-=600')
        .add({ targets: '#commands-card', opacity: [0, 1], translateY: [20, 0], duration: 800 }, '-=600');

    // --- File Explorer Logic ---
    const explorerChannelSelect = document.getElementById('explorer-channel');
    const fileListContainer = document.getElementById('file-list');
    const refreshButton = document.getElementById('refresh-files');
    const downloadForm = document.querySelector('#download-card form');

    const loadFiles = async () => {
        const channelName = explorerChannelSelect.value;
        if (!channelName) return;

        fileListContainer.innerHTML = '<div class="flex items-center justify-center h-full"><i class="fa-solid fa-circle-notch fa-spin text-2xl text-violet-500"></i></div>';

        try {
            const response = await fetch('/list_files', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ server_id: SERVER_ID, channel_name: channelName })
            });
            const data = await response.json();

            fileListContainer.innerHTML = '';

            if (data.files && data.files.length > 0) {
                data.files.forEach((file, index) => {
                    const isFolder = file.upload_type === 'folder';
                    const iconClass = isFolder ? 'fa-folder text-fuchsia-400' : 'fa-file-lines text-violet-400';
                    const size = file.original_size || file.total_size || 0;

                    const el = document.createElement('div');
                    el.className = 'file-item grid grid-cols-12 gap-4 px-4 py-3 rounded-lg items-center cursor-pointer group opacity-0';
                    el.innerHTML = `
                        <div class="col-span-6 flex items-center gap-3 overflow-hidden">
                            <div class="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0">
                                <i class="fa-regular ${iconClass}"></i>
                            </div>
                            <div class="truncate">
                                <div class="text-sm font-medium text-slate-200 truncate group-hover:text-white transition-colors">
                                    ${file.original_filename || file.folder_name}
                                </div>
                                <div class="text-[10px] text-slate-500 uppercase">${isFolder ? 'Folder' : (file.encrypted ? 'Encrypted' : 'Standard')}</div>
                            </div>
                        </div>
                        <div class="col-span-2 text-right text-xs text-slate-400 font-mono">${formatSize(size)}</div>
                        <div class="col-span-2 text-right text-xs text-slate-400 opacity-70">${formatDate(file.upload_date)}</div>
                        <div class="col-span-2 flex justify-end gap-2">
                            <button class="download-btn p-2 rounded-lg hover:bg-violet-600 text-slate-400 hover:text-white transition-all transform hover:scale-110 active:scale-95" title="Download">
                                <i class="fa-solid fa-download"></i>
                            </button>
                            <button class="delete-btn p-2 rounded-lg hover:bg-red-600 text-slate-400 hover:text-white transition-all transform hover:scale-110 active:scale-95" title="Delete">
                                <i class="fa-solid fa-trash"></i>
                            </button>
                        </div>
                    `;

                    // Attach Download Event
                    const downloadBtn = el.querySelector('.download-btn');
                    downloadBtn.onclick = (e) => {
                        e.stopPropagation();
                        triggerDownload(file, channelName);
                    };

                    // Attach Delete Event
                    const deleteBtn = el.querySelector('.delete-btn');
                    deleteBtn.onclick = (e) => {
                        e.stopPropagation();
                        triggerDelete(file, channelName);
                    };

                    fileListContainer.appendChild(el);
                });

                // Staggered Animation for list items
                anime({
                    targets: '.file-item',
                    opacity: [0, 1],
                    translateY: [10, 0],
                    delay: anime.stagger(50),
                    duration: 400,
                    easing: 'easeOutQuad'
                });

            } else {
                fileListContainer.innerHTML = `
                    <div class="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
                        <i class="fa-regular fa-folder-open text-3xl opacity-30"></i>
                        <span class="text-sm">No files found in this channel</span>
                    </div>`;
            }
        } catch (error) {
            console.error(error);
            fileListContainer.innerHTML = '<div class="text-red-400 text-center text-sm p-4">Failed to load files</div>';
        }
    };

    const triggerDownload = (file, channelName) => {
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = '/download';

        const inputServer = document.createElement('input');
        inputServer.type = 'hidden';
        inputServer.name = 'server_id';
        inputServer.value = SERVER_ID;

        const inputFiles = document.createElement('input');
        inputFiles.type = 'hidden';
        inputFiles.name = 'files';
        inputFiles.value = file.folder_name ? `${file.folder_name}/` : file.original_filename;

        const inputChannel = document.createElement('input');
        inputChannel.type = 'hidden';
        inputChannel.name = 'channels';
        inputChannel.value = channelName; // Uses the channel where it was found

        form.appendChild(inputServer);
        form.appendChild(inputFiles);
        form.appendChild(inputChannel);
        document.body.appendChild(form);
        form.submit();
        document.body.removeChild(form);
    };

    const triggerDelete = async (file, channelName) => {
        const fileName = file.folder_name || file.original_filename;
        if (!confirm(`Are you sure you want to delete "${fileName}"? This action cannot be undone.`)) {
            return;
        }

        try {
            const response = await fetch('/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    server_id: SERVER_ID,
                    filename: file.folder_name ? `${file.folder_name}/` : file.original_filename,
                    channel_name: channelName
                })
            });

            const result = await response.json();

            if (response.ok) {
                showNotification('success', result.message);
                await loadFiles();
            } else {
                showNotification('error', result.message || 'Delete failed');
            }
        } catch (error) {
            console.error('Delete error:', error);
            showNotification('error', 'Error deleting file: ' + error.message);
        }
    };

    const showNotification = (type, message) => {
        const notification = document.createElement('div');
        notification.className = `fixed top-4 right-4 px-4 py-3 rounded-lg text-sm font-medium ${type === 'success' ? 'bg-green-500/20 text-green-300 border border-green-500/30' : 'bg-red-500/20 text-red-300 border border-red-500/30'
            } z-50 animate-fadeIn`;
        notification.innerHTML = `<i class="fa-solid fa-${type === 'success' ? 'check' : 'exclamation'} mr-2"></i>${message}`;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'fadeOut 0.3s ease forwards';
            setTimeout(() => notification.remove(), 300);
        }, 4000);
    };

    explorerChannelSelect.addEventListener('change', loadFiles);
    refreshButton.addEventListener('click', () => {
        const icon = refreshButton.querySelector('i');
        icon.classList.add('fa-spin');
        loadFiles().then(() => setTimeout(() => icon.classList.remove('fa-spin'), 500));
    });

    // Load initial files if channel selected
    if (explorerChannelSelect.value) loadFiles();


    // --- Upload Logic ---
    const fileInput = document.getElementById('file-input');
    const folderInput = document.getElementById('folder-input');
    const uploadButton = document.getElementById('upload-button');
    const stagingArea = document.getElementById('staging-area');
    const fileCountSpan = document.getElementById('file-count');
    const uploadStatus = document.getElementById('upload-status');
    const folderNameContainer = document.getElementById('folder-name-container');
    const folderNameInput = document.getElementById('folder-name-input');

    let stagedFiles = [];
    let isFolderUpload = false;

    const updateStagingArea = () => {
        if (stagedFiles.length === 0) {
            stagingArea.innerHTML = '<div class="h-full flex items-center justify-center italic opacity-50">No files selected</div>';
            uploadButton.disabled = true;
            folderNameContainer.classList.add('hidden');
            isFolderUpload = false;
        } else {
            // Check if this is a folder upload (files have webkitRelativePath)
            isFolderUpload = stagedFiles.some(f => f.webkitRelativePath);
            folderNameContainer.classList.toggle('hidden', !isFolderUpload);

            // Auto-populate folder name from first file's path if not set
            if (isFolderUpload && !folderNameInput.value) {
                const firstPath = stagedFiles[0].webkitRelativePath;
                const folderName = firstPath.split('/')[0];
                folderNameInput.value = folderName;
            }

            stagingArea.innerHTML = '';
            stagedFiles.forEach((file, i) => {
                const fileEl = document.createElement('div');
                fileEl.className = 'flex justify-between items-center group bg-white/5 p-2 rounded hover:bg-white/10 transition-colors cursor-default';
                fileEl.innerHTML = `
                    <span class="truncate pr-2">${file.webkitRelativePath || file.name}</span>
                    <button onclick="removeFile(${i})" class="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300 transition-all">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                `;
                stagingArea.appendChild(fileEl);
            });
            uploadButton.disabled = false;
        }
        fileCountSpan.textContent = stagedFiles.length;

        // Animate numbers
        anime({
            targets: fileCountSpan,
            scale: [1.2, 1],
            color: ['#fff', '#cbd5e1'],
            duration: 300
        });

    };

    window.removeFile = (index) => {
        stagedFiles.splice(index, 1);
        updateStagingArea();
    };

    const addFilesToStage = (files) => {
        const newFiles = Array.from(files).filter(file =>
            !stagedFiles.some(stagedFile => (stagedFile.webkitRelativePath || stagedFile.name) === (file.webkitRelativePath || file.name))
        );
        stagedFiles.push(...newFiles);
        updateStagingArea();
    };

    fileInput.addEventListener('change', (e) => { addFilesToStage(e.target.files); fileInput.value = ''; });
    folderInput.addEventListener('change', (e) => { addFilesToStage(e.target.files); folderInput.value = ''; });

    uploadButton.addEventListener('click', async () => {
        if (stagedFiles.length === 0) return;

        uploadButton.disabled = true;
        uploadButton.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Uploading...';
        uploadStatus.textContent = '';
        uploadStatus.className = 'text-center mt-3 text-xs font-medium min-h-[20px] text-violet-400';

        const formData = new FormData();
        formData.append('server_id', SERVER_ID);
        formData.append('channel', document.getElementById('upload-channel').value);
        formData.append('encrypt', document.getElementById('encrypt-checkbox').checked);

        // Add folder name if this is a folder upload
        if (isFolderUpload && folderNameInput.value) {
            formData.append('folder_name', folderNameInput.value);
        }

        stagedFiles.forEach(file => {
            const fileName = file.webkitRelativePath || file.name;
            formData.append('files[]', file, fileName);
        });

        try {
            const response = await fetch('/upload', { method: 'POST', body: formData });
            const result = await response.json();

            if (response.ok) {
                uploadStatus.innerHTML = '<span class="text-green-400"><i class="fa-solid fa-check"></i> ' + result.message + '</span>';
                stagedFiles = [];
                folderNameInput.value = '';
                updateStagingArea();
                // Refresh file list if same channel
                if (document.getElementById('explorer-channel').value === document.getElementById('upload-channel').value) {
                    loadFiles();
                }
            } else {
                throw new Error(result.message || 'Upload failed');
            }
        } catch (error) {
            uploadStatus.innerHTML = '<span class="text-red-400"><i class="fa-solid fa-triangle-exclamation"></i> ' + error.message + '</span>';
        } finally {
            uploadButton.innerHTML = '<span>Start Upload</span><i class="fa-solid fa-paper-plane"></i>';
            if (stagedFiles.length > 0) uploadButton.disabled = false;
        }
    });
});
