document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('report-form');
  const photoInput = document.getElementById('photo-input');
  const previews = document.getElementById('previews');
  const submitBtn = document.getElementById('submit-btn');
  const resultDiv = document.getElementById('result');
  const moreImagesDiv = document.getElementById('more-images');
  const moreImagesMsg = document.getElementById('more-images-msg');

  let selectedFiles = [];

  photoInput.addEventListener('change', (e) => {
    const newFiles = Array.from(e.target.files);
    const remaining = 3 - selectedFiles.length;
    selectedFiles.push(...newFiles.slice(0, remaining));
    renderPreviews();
    photoInput.value = '';
  });

  function renderPreviews() {
    previews.innerHTML = '';
    selectedFiles.forEach((file, i) => {
      const wrapper = document.createElement('div');
      wrapper.className = 'preview-wrapper';

      const img = document.createElement('img');
      img.className = 'preview-thumb';
      img.src = URL.createObjectURL(file);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'remove-btn';
      removeBtn.innerHTML = '&times;';
      removeBtn.onclick = () => { selectedFiles.splice(i, 1); renderPreviews(); };

      wrapper.appendChild(img);
      wrapper.appendChild(removeBtn);
      previews.appendChild(wrapper);
    });

    document.getElementById('add-photo-btn').style.display = selectedFiles.length >= 3 ? 'none' : 'flex';
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (selectedFiles.length === 0) {
      alert('Please add at least one photo.');
      return;
    }

    submitBtn.classList.add('btn-loading');
    submitBtn.disabled = true;
    resultDiv.classList.add('hidden');
    moreImagesDiv.classList.add('hidden');

    const fd = new FormData();
    selectedFiles.forEach(f => fd.append('images', f));
    fd.append('location', document.getElementById('location').value);
    fd.append('reported_by', document.getElementById('reported_by').value);

    try {
      const res = await fetch('/api/report', { method: 'POST', body: fd });
      const data = await res.json();

      if (data.needs_more_images) {
        moreImagesMsg.textContent = data.message;
        moreImagesDiv.classList.remove('hidden');
      } else if (data.success) {
        const item = data.item;
        resultDiv.innerHTML = `
          <div class="success-card">
            <h3><i class="bi bi-check-circle"></i> Item Reported!</h3>
            <p><strong>${item.item_name}</strong> (${item.category})</p>
            <p class="card-desc">${item.description}</p>
            <p class="card-meta">Color: ${item.color} | Brand: ${item.brand} | Size: ${item.size}</p>
          </div>`;
        resultDiv.classList.remove('hidden');
        form.reset();
        selectedFiles = [];
        renderPreviews();
      } else {
        resultDiv.innerHTML = `<div class="error">${data.error || 'Unknown error'}</div>`;
        resultDiv.classList.remove('hidden');
      }
    } catch (err) {
      resultDiv.innerHTML = `<div class="error">Network error. Please try again.</div>`;
      resultDiv.classList.remove('hidden');
    } finally {
      submitBtn.classList.remove('btn-loading');
      submitBtn.disabled = false;
    }
  });
});
