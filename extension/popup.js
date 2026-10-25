const SUPPORTED = {
  "facebook.com": { required: ["c_user", "xs"] },
  "instagram.com": { required: ["sessionid"] },
  "tiktok.com": { required: ["sessionid"] },
  "youtube.com": { required: [] },
};

function rootDomain(host) {
  const parts = host.split(".");
  const two = ["co", "com"];
  // facebook.com / instagram.com / tiktok.com / youtube.com — plain 2LD
  for (const dom of Object.keys(SUPPORTED)) {
    if (host === dom || host.endsWith("." + dom)) return dom;
  }
  return parts.slice(-2).join(".");
}

function cookieHeader(domain, cb) {
  chrome.cookies.getAll({ domain }, function (cookies) {
    // include cookies set on parent domains too (e.g. .facebook.com)
    const seen = new Map();
    for (const c of cookies) seen.set(c.name, c.value);
    const header = [...seen.entries()].map(([k, v]) => k + "=" + v).join("; ");
    cb(header, seen);
  });
}

chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
  const tab = tabs[0];
  if (!tab || !tab.url) {
    document.getElementById("site").textContent = "No active tab.";
    return;
  }
  let host;
  try { host = new URL(tab.url).hostname; } catch (e) { host = ""; }
  const dom = rootDomain(host);
  document.getElementById("site").textContent = host || "(unknown)";

  if (!SUPPORTED[dom]) {
    document.getElementById("count").textContent =
      "Open facebook.com / instagram.com / tiktok.com / youtube.com first.";
    return;
  }

  cookieHeader(dom, function (header, seen) {
    const countEl = document.getElementById("count");
    const keysEl = document.getElementById("keys");
    countEl.innerHTML = "<b>" + seen.size + "</b> cookies found for " + dom;
    const req = SUPPORTED[dom].required;
    if (req.length) {
      const missing = req.filter((k) => !seen.has(k));
      keysEl.innerHTML = req
        .map((k) =>
          seen.has(k)
            ? "✔ <b>" + k + "</b> present"
            : '<span class="miss">✘ ' + k + " missing (not logged in?)</span>"
        )
        .join("<br>");
      if (missing.length) {
        document.getElementById("status").className = "status err";
        document.getElementById("status").textContent =
          "Cookie will likely fail — log in to " + dom + " first.";
      }
    }

    function copyToClipboard(text, after) {
      // MV3 service-worker-free approach: use the popup document
      navigator.clipboard.writeText(text).then(after, function () {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
        after();
      });
    }

    document.getElementById("copy").addEventListener("click", function () {
      if (!header) {
        document.getElementById("status").className = "status err";
        document.getElementById("status").textContent = "No cookies to copy.";
        return;
      }
      copyToClipboard(header, function () {
        const s = document.getElementById("status");
        s.className = "status ok";
        s.textContent = "Copied! (" + header.length + " chars) — paste into Hans Downloader Advanced.";
      });
    });

    document.getElementById("copyopen").addEventListener("click", function () {
      copyToClipboard(header, function () {
        chrome.tabs.create({ url: "https://sosgrab.vercel.app/" });
        const s = document.getElementById("status");
        s.className = "status ok";
        s.textContent = "Copied & Hans Downloader opened — paste into Advanced.";
      });
    });
  });
});
