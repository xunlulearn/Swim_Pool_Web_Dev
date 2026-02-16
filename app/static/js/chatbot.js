(() => {
    const input = document.getElementById("chatbot-input");
    const sendBtn = document.getElementById("chatbot-send");
    const statusEl = document.getElementById("chatbot-status");
    const replyEl = document.getElementById("chatbot-reply");
    const sourcesWrap = document.getElementById("chatbot-sources-wrap");
    const sourcesEl = document.getElementById("chatbot-sources");

    if (!input || !sendBtn || !statusEl || !replyEl || !sourcesWrap || !sourcesEl) {
        return;
    }

    const getCsrfToken = () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return (meta?.getAttribute("content") || "").trim();
    };

    const setLoading = (isLoading) => {
        sendBtn.disabled = isLoading;
        sendBtn.textContent = isLoading ? "Thinking..." : "Ask";
        statusEl.textContent = isLoading ? "Sending request..." : "";
    };

    const renderSources = (sources) => {
        sourcesEl.innerHTML = "";
        if (!Array.isArray(sources) || sources.length === 0) {
            sourcesWrap.classList.add("hidden");
            return;
        }

        sources.forEach((source) => {
            if (typeof source !== "string" || !source.trim()) {
                return;
            }
            const li = document.createElement("li");
            const a = document.createElement("a");
            a.href = source;
            a.textContent = source;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.className = "text-ntu-blue hover:underline break-all";
            li.appendChild(a);
            sourcesEl.appendChild(li);
        });

        sourcesWrap.classList.toggle("hidden", sourcesEl.children.length === 0);
    };

    const ask = async () => {
        const message = input.value.trim();
        if (!message) {
            statusEl.textContent = "Please enter a question.";
            return;
        }

        const csrfToken = getCsrfToken();
        if (!csrfToken) {
            statusEl.textContent = "Missing CSRF token. Please refresh the page.";
            return;
        }

        setLoading(true);
        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                body: JSON.stringify({ message }),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const errorMsg = data?.error || `Request failed (${response.status})`;
                replyEl.textContent = errorMsg;
                renderSources([]);
                statusEl.textContent = "";
                return;
            }

            const reply = typeof data?.reply === "string" ? data.reply.trim() : "";
            replyEl.textContent = reply || "No reply returned.";
            renderSources(data?.sources || []);
            statusEl.textContent = "Done.";
        } catch (_error) {
            replyEl.textContent = "Request failed. Please try again.";
            renderSources([]);
            statusEl.textContent = "";
        } finally {
            setLoading(false);
        }
    };

    sendBtn.addEventListener("click", ask);
    input.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            event.preventDefault();
            ask();
        }
    });
})();
