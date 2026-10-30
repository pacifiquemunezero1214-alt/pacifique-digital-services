
document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.getElementById("sidebar");
    const menuToggle = document.getElementById("menuToggle");

    // Mobile sidebar toggle
    if (sidebar && menuToggle) {
        menuToggle.addEventListener("click", () => {
            sidebar.classList.toggle("open");
        });

        // Close sidebar when clicking outside it on mobile
        document.addEventListener("click", (event) => {
            const isMobile = window.matchMedia("(max-width: 900px)").matches;

            if (
                isMobile &&
                sidebar.classList.contains("open") &&
                !sidebar.contains(event.target) &&
                !menuToggle.contains(event.target)
            ) {
                sidebar.classList.remove("open");
            }
        });

        // Reset sidebar when switching to desktop layout
        window.addEventListener("resize", () => {
            if (window.innerWidth > 900) {
                sidebar.classList.remove("open");
            }
        });
    }

    // Automatically dismiss flash messages after 5 seconds
    document.querySelectorAll(".flash-message").forEach((message) => {
        window.setTimeout(() => {
            message.style.transition = "opacity 0.3s ease";
            message.style.opacity = "0";

            window.setTimeout(() => {
                message.remove();
            }, 350);
        }, 5000);
    });

    // Confirm before submitting forms marked with data-confirm
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            const message =
                form.getAttribute("data-confirm") ||
                "Are you sure you want to continue?";

            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });
});
