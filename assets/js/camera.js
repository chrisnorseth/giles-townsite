(() => {
  const viewer = document.querySelector('#camera-viewer');
  if (!viewer || typeof viewer.showModal !== 'function') return;
  const photos = Array.from(document.querySelectorAll('[data-camera-photo]'));
  const image = document.querySelector('#camera-viewer-image');
  const caption = document.querySelector('#camera-viewer-caption');
  const previous = viewer.querySelector('[data-camera-previous]');
  const next = viewer.querySelector('[data-camera-next]');
  let index = 0;
  function show(position) {
    index = position;
    image.src = photos[index].href;
    image.alt = `River crossing on ${photos[index].dataset.label}`;
    caption.textContent = photos[index].dataset.label;
    previous.disabled = index === 0;
    next.disabled = index === photos.length - 1;
  }
  photos.forEach((photo, position) => photo.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    show(position);
    viewer.showModal();
  }));
  viewer.querySelector('[data-camera-close]').addEventListener('click', () => viewer.close());
  previous.addEventListener('click', () => { if (index > 0) show(index - 1); });
  next.addEventListener('click', () => { if (index < photos.length - 1) show(index + 1); });
  viewer.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' && index > 0) { event.preventDefault(); show(index - 1); }
    if (event.key === 'ArrowRight' && index < photos.length - 1) { event.preventDefault(); show(index + 1); }
  });
})();
