let lastUpdated = null;

function updateQRImage() {
  const img = document.getElementById('qr-image');
  const timestamp = new Date().getTime(); // Avoid caching
  img.src = /static/qr_display/latest_qr.png?t=${timestamp};
  document.getElementById('token-info').textContent = "✅ New QR Token Generated!";
}

function pollServer() {
  fetch('/check-new-token')
    .then(res => res.json())
    .then(data => {
      if (data.updated !== lastUpdated) {
        lastUpdated = data.updated;
        updateQRImage();
      }
    })
    .catch(err => {
      console.error("Polling error:", err);
    });
}

// Poll every 2 seconds
setInterval(pollServer, 2000);
#script.js