(() => {
  const STORE = "gt-likes";
  const all = () => { try { return JSON.parse(localStorage.getItem(STORE)) || {}; } catch { return {}; } };
  function refresh() {
    const liked = all();
    document.querySelectorAll(".like[data-key]").forEach(b => {
      const on = b.dataset.key in liked;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on);
      b.textContent = on ? "♥ いいね済み" : "♡ いいね";
    });
    const n = Object.keys(liked).length;
    document.querySelectorAll(".likes-count").forEach(el => el.textContent = n || "");
  }
  function toggle(key, repo) {
    const liked = all();
    if (liked[key]) delete liked[key]; else liked[key] = { repo, at: new Date().toISOString() };
    localStorage.setItem(STORE, JSON.stringify(liked));
    refresh();
  }
  document.addEventListener("click", ev => {
    const b = ev.target.closest(".like[data-key]");
    if (b) { ev.preventDefault(); toggle(b.dataset.key, b.dataset.repo); }
  });
  window.addEventListener("storage", ev => { if (ev.key === STORE) refresh(); });
  window.Likes = { all, refresh };
  refresh();
})();
