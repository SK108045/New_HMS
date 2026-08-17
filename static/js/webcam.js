/**
 * Hospital Front-Desk Webcam Photo Capture Controller
 * Manages HTML5 webcam streaming, frame capture, preview, and base64 payload binding.
 */

let activeStream = null;

function initWebcam(videoElId = 'webcam-video', placeholderElId = 'webcam-placeholder', captureBtnId = 'btn-capture-photo') {
    const video = document.getElementById(videoElId);
    const placeholder = document.getElementById(placeholderElId);
    const captureBtn = document.getElementById(captureBtnId);

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert("Webcam capture is not supported by this browser. Please use file upload instead.");
        return;
    }

    // Request 4:3 clinical aspect ratio stream
    navigator.mediaDevices.getUserMedia({
        video: {
            width: { ideal: 640 },
            height: { ideal: 480 },
            facingMode: 'user'
        },
        audio: false
    })
    .then(stream => {
        activeStream = stream;
        if (video) {
            video.srcObject = stream;
            video.play();
            video.classList.remove('hidden');
        }
        if (placeholder) {
            placeholder.classList.add('hidden');
        }
        if (captureBtn) {
            captureBtn.disabled = false;
        }
    })
    .catch(err => {
        console.error("Camera access error:", err);
        alert("Unable to access front-desk camera: " + err.message + ". Please ensure camera permissions are granted.");
    });
}

function captureSnapshot(videoElId = 'webcam-video', previewImgId = 'photo-preview', hiddenInputId = 'webcam_image', retakeBtnId = 'btn-retake-photo', captureBtnId = 'btn-capture-photo') {
    const video = document.getElementById(videoElId);
    const previewImg = document.getElementById(previewImgId);
    const hiddenInput = document.getElementById(hiddenInputId);
    const retakeBtn = document.getElementById(retakeBtnId);
    const captureBtn = document.getElementById(captureBtnId);

    if (!video || !activeStream) return;

    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;

    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const dataUrl = canvas.toDataURL('image/jpeg', 0.85);

    if (hiddenInput) {
        hiddenInput.value = dataUrl;
    }
    if (previewImg) {
        previewImg.src = dataUrl;
        previewImg.classList.remove('hidden');
    }
    if (video) {
        video.classList.add('hidden');
    }
    if (captureBtn) {
        captureBtn.classList.add('hidden');
    }
    if (retakeBtn) {
        retakeBtn.classList.remove('hidden');
    }

    // Stop stream tracks to free hardware
    stopWebcamTracks();
}

function retakeSnapshot(videoElId = 'webcam-video', previewImgId = 'photo-preview', hiddenInputId = 'webcam_image', retakeBtnId = 'btn-retake-photo', captureBtnId = 'btn-capture-photo', placeholderElId = 'webcam-placeholder') {
    const previewImg = document.getElementById(previewImgId);
    const hiddenInput = document.getElementById(hiddenInputId);
    const retakeBtn = document.getElementById(retakeBtnId);
    const captureBtn = document.getElementById(captureBtnId);

    if (hiddenInput) {
        hiddenInput.value = '';
    }
    if (previewImg) {
        previewImg.classList.add('hidden');
        previewImg.src = '';
    }
    if (retakeBtn) {
        retakeBtn.classList.add('hidden');
    }
    if (captureBtn) {
        captureBtn.classList.remove('hidden');
        captureBtn.disabled = false;
    }

    initWebcam(videoElId, placeholderElId, captureBtnId);
}

function stopWebcamTracks() {
    if (activeStream) {
        activeStream.getTracks().forEach(track => track.stop());
        activeStream = null;
    }
}

// Ensure camera is turned off when leaving the page
window.addEventListener('beforeunload', stopWebcamTracks);
