document.addEventListener('DOMContentLoaded', () => {
  const textForm = document.getElementById('text-search-form');
  const imageForm = document.getElementById('image-search-form');
  const searchPhotoInput = document.getElementById('search-photo-input');
  const searchPreview = document.getElementById('search-preview');
  const imageSearchBtn = document.getElementById('image-search-btn');
  const resultsDiv = document.getElementById('search-results');
  const loadingDiv = document.getElementById('search-loading');
  const tpl = document.getElementById('result-card');

  let searchImageFile = null;

  searchPhotoInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    searchImageFile = file;
    searchPreview.innerHTML = `<img src="${URL.createObjectURL(file)}" class="preview-thumb preview-thumb-lg">`;
    imageSearchBtn.disabled = false;
  });

  textForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = document.getElementById('search-query').value.trim();
    if (!query) return;

    showLoading();
    try {
      const res = await fetch('/api/search/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });
      const data = await res.json();
      renderResults(data.items || []);
    } catch (err) {
      resultsDiv.innerHTML = '<div class="error">Search failed. Please try again.</div>';
    } finally {
      hideLoading();
    }
  });

  imageForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!searchImageFile) return;

    showLoading();
    const fd = new FormData();
    fd.append('image', searchImageFile);

    try {
      const res = await fetch('/api/search/image', { method: 'POST', body: fd });
      const data = await res.json();
      renderResults(data.items || []);
    } catch (err) {
      resultsDiv.innerHTML = '<div class="error">Search failed. Please try again.</div>';
    } finally {
      hideLoading();
    }
  });

  function showLoading() {
    loadingDiv.classList.remove('hidden');
    resultsDiv.innerHTML = '';
  }

  function hideLoading() {
    loadingDiv.classList.add('hidden');
  }

  function renderResults(items) {
    if (items.length === 0) {
      resultsDiv.innerHTML = '<div class="empty-state"><i class="bi bi-search"></i><p>No matching items found.</p></div>';
      return;
    }

    resultsDiv.innerHTML = `<p class="hint">${items.length} item(s) found</p>`;
    items.forEach(item => {
      const clone = tpl.content.cloneNode(true);
      const card = clone.querySelector('.result-card');
      const img = clone.querySelector('.result-img');
      const thumbUrl = (item.thumb_urls && item.thumb_urls[0]) || (item.image_urls && item.image_urls[0]) || '';
      img.src = thumbUrl;
      img.alt = item.item_name;
      clone.querySelector('.result-name').textContent = item.item_name;
      clone.querySelector('.result-category').textContent = item.category;
      clone.querySelector('.result-desc').textContent = (item.description || '').slice(0, 120);
      clone.querySelector('.result-color').innerHTML = '<i class="bi bi-palette"></i> ' + (item.color || 'N/A');
      clone.querySelector('.result-location').innerHTML = '<i class="bi bi-geo-alt"></i> ' + (item.location_found || 'N/A');
      clone.querySelector('.result-date').innerHTML = '<i class="bi bi-clock"></i> ' + new Date(item.found_date).toLocaleDateString();
      card.style.cursor = 'pointer';
      card.addEventListener('click', () => openModal(item));
      resultsDiv.appendChild(clone);
    });
  }
});

function openModal(item) {
  document.getElementById('modal-img').src = (item.image_urls && item.image_urls[0]) || '';
  document.getElementById('modal-name').textContent = item.item_name;
  document.getElementById('modal-category').textContent = item.category;
  document.getElementById('modal-status').textContent = item.status || 'unclaimed';
  document.getElementById('modal-desc').textContent = item.description || '';
  document.getElementById('modal-color').textContent = item.color || 'N/A';
  document.getElementById('modal-brand').textContent = item.brand || 'N/A';
  document.getElementById('modal-size').textContent = item.size || 'N/A';
  document.getElementById('modal-condition').textContent = item.condition || 'N/A';
  document.getElementById('modal-location').textContent = item.location_found || 'N/A';
  document.getElementById('modal-date').textContent = new Date(item.found_date).toLocaleString();
  document.getElementById('modal-reporter').textContent = item.reported_by || 'N/A';
  document.getElementById('modal-features').textContent = item.distinguishing_features || 'None';
  document.getElementById('detail-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('detail-modal').classList.add('hidden');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
