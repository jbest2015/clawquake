/* ClawQuake — Global theme toggle (light/dark)
   Include via <script src="/theme.js"></script> after </body> or at end of <body>.
   Reads/writes localStorage key "clawquake_theme". */

(function () {
    var STORAGE_KEY = "clawquake_theme";

    function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        var btn = document.getElementById("cq-theme-toggle");
        if (btn) btn.textContent = theme === "light" ? "Dark" : "Light";
    }

    function toggle() {
        var current = document.documentElement.getAttribute("data-theme") || "dark";
        var next = current === "dark" ? "light" : "dark";
        localStorage.setItem(STORAGE_KEY, next);
        applyTheme(next);
    }

    // Apply saved preference immediately (before paint)
    var saved = localStorage.getItem(STORAGE_KEY) || "dark";
    applyTheme(saved);

    // Inject toggle button into .user-info (first one found)
    document.addEventListener("DOMContentLoaded", function () {
        var container = document.querySelector(".header .user-info");
        if (!container) return;

        var btn = document.createElement("button");
        btn.id = "cq-theme-toggle";
        btn.className = "theme-toggle";
        btn.textContent = saved === "light" ? "Dark" : "Light";
        btn.addEventListener("click", toggle);
        container.insertBefore(btn, container.firstChild);
    });
})();
