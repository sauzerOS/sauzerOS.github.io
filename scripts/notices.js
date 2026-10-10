// Build server notices (notices.json, written by hokuto: a held python
// upgrade, for instance), shown in the page's #notices element.
(function () {
  const target = document.getElementById("notices");
  if (!target) return;

  const style = document.createElement("style");
  style.textContent = `
    .notice {
      background-color: #eee8d5;
      border-left: 4px solid #cb4b16;
      padding: 8px 12px;
      margin: 0 0 16px;
      max-width: 1100px;
    }
    .notice.ok { border-left-color: #859900; }
    .notice-title { color: #cb4b16; font-weight: bold; }
    .notice.ok .notice-title { color: #859900; }
    .notice-time { color: #93a1a1; font-size: 0.85em; }
  `;
  document.head.appendChild(style);

  fetch("notices.json", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => [])
    .then((notices) => {
      for (const notice of notices || []) {
        const box = document.createElement("div");
        box.className = "notice" + (notice.level === "ok" ? " ok" : "");
        const title = document.createElement("div");
        title.className = "notice-title";
        title.textContent = notice.title || "";
        const text = document.createElement("div");
        text.textContent = notice.text || "";
        box.append(title, text);
        if (notice.updated) {
          const time = document.createElement("div");
          time.className = "notice-time";
          time.textContent = "updated " + new Date(notice.updated).toISOString().slice(0, 16).replace("T", " ") + " UTC";
          box.append(time);
        }
        target.append(box);
      }
    });
})();
