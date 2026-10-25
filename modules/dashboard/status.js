// Live up/down dots for dashboard tiles. The page works without this script.
const TIMEOUT_MS = 3000;
const INTERVAL_MS = 15000;

async function check(tile) {
  const dot = tile.querySelector(".dot");
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  let state = "down";
  try {
    const res = await fetch(tile.dataset.health, { cache: "no-store", redirect: "manual", signal: ctrl.signal });
    // 2xx/3xx = up; a 3xx arrives as an "opaqueredirect" with status 0
    if (res.type === "opaqueredirect" || (res.status >= 200 && res.status < 400)) state = "up";
  } catch (_) {
    // network error or timeout → down
  }
  clearTimeout(timer);
  dot.dataset.state = state;
  dot.setAttribute("aria-label", "status: " + state);
}

function checkAll() {
  document.querySelectorAll("[data-health]").forEach(check);
}

checkAll();
setInterval(checkAll, INTERVAL_MS);
