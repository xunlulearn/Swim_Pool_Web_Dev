(() => {
    const launcher = document.getElementById("chatbot-launcher");
    const panel = document.getElementById("chatbot-panel");
    const closeBtn = document.getElementById("chatbot-close");
    const backdrop = document.getElementById("chatbot-backdrop");
    const thread = document.getElementById("chatbot-thread");
    const input = document.getElementById("chatbot-input");
    const sendBtn = document.getElementById("chatbot-send");
    const statusEl = document.getElementById("chatbot-status");
    const loginLink = document.getElementById("chatbot-login-link");

    const hint = document.getElementById("chatbot-hint");
    const hintDismissBtn = document.getElementById("chatbot-hint-dismiss");
    const hintNeverCheckbox = document.getElementById("chatbot-hint-never");

    const UI_TEXT = {
        en: {
            send: "Send",
            sending: "Sending...",
            assistantThinking: "Assistant is thinking",
            assistantTyping: "Assistant is typing",
            done: "Done.",
            loginRequired: "Please log in to chat with NTU Pool Assistant.",
            chatUnavailable: "Chat composer is unavailable.",
            enterQuestion: "Please enter a question.",
            missingCsrf: "Missing CSRF token. Please refresh the page.",
            streamUnavailable: "Streaming is unavailable. Please try again.",
            noReply: "No reply returned.",
            requestFailed: "Request failed. Please try again.",
            streamingFailed: "Streaming request failed.",
            quickQuestionsTitle: "You can try asking me:",
            thinkingLabel: "Thinking",
            feedbackPrompt:
                "Please rate this answer to help me improve future responses.",
            feedbackPlaceholder: "Share your feedback (optional)",
            feedbackTapToRate: "Tap a star to submit your rating.",
            feedbackSubmitting: "Submitting rating...",
            feedbackThanks: "Thanks for your feedback!",
            feedbackFailed: "Unable to submit rating. Please try again.",
        },
        zh: {
            send: "\u53d1\u9001",
            sending: "\u53d1\u9001\u4e2d...",
            assistantThinking: "\u52a9\u624b\u6b63\u5728\u601d\u8003",
            assistantTyping: "\u52a9\u624b\u6b63\u5728\u8f93\u51fa",
            done: "\u5df2\u5b8c\u6210\u3002",
            loginRequired:
                "\u8bf7\u5148\u767b\u5f55\u540e\u518d\u4f7f\u7528 NTU Pool Assistant\u3002",
            chatUnavailable: "\u804a\u5929\u8f93\u5165\u6846\u6682\u4e0d\u53ef\u7528\u3002",
            enterQuestion: "\u8bf7\u8f93\u5165\u4f60\u7684\u95ee\u9898\u3002",
            missingCsrf: "\u7f3a\u5c11 CSRF token\uff0c\u8bf7\u5237\u65b0\u9875\u9762\u540e\u91cd\u8bd5\u3002",
            streamUnavailable: "\u6d41\u5f0f\u8f93\u51fa\u4e0d\u53ef\u7528\uff0c\u8bf7\u91cd\u8bd5\u3002",
            noReply: "\u6682\u672a\u8fd4\u56de\u56de\u7b54\u3002",
            requestFailed: "\u8bf7\u6c42\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002",
            streamingFailed: "\u6d41\u5f0f\u8bf7\u6c42\u5931\u8d25\u3002",
            quickQuestionsTitle: "\u4f60\u53ef\u4ee5\u8bd5\u7740\u95ee\u6211\uff1a",
            thinkingLabel: "\u601d\u8003\u4e2d",
            feedbackPrompt:
                "\u8bf7\u5bf9\u6211\u8fdb\u884c\u6ee1\u610f\u5ea6\u8bc4\u5206\uff0c\u5e2e\u52a9\u6211\u4ee5\u540e\u56de\u7b54\u5f97\u66f4\u597d\u3002",
            feedbackPlaceholder: "\u6b22\u8fce\u8f93\u5165\u53cd\u9988\u610f\u89c1\uff08\u9009\u586b\uff09",
            feedbackTapToRate: "\u70b9\u51fb\u661f\u661f\u5373\u53ef\u63d0\u4ea4\u8bc4\u5206\u3002",
            feedbackSubmitting: "\u6b63\u5728\u63d0\u4ea4\u8bc4\u5206...",
            feedbackThanks: "\u611f\u8c22\u53cd\u9988\uff01",
            feedbackFailed: "\u63d0\u4ea4\u8bc4\u5206\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002",
        },
    };
    const CJK_CHAR_RE = /[\u3400-\u9fff]/;
    const LATIN_CHAR_RE = /[a-z]/i;
    const prefersReducedMotion =
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false;

    if (!launcher || !panel || !closeBtn || !backdrop || !thread || !statusEl) {
        return;
    }

    const isAuthenticated = panel.dataset.authenticated === "true";
    const userKey = (panel.dataset.userKey || (isAuthenticated ? "user" : "guest")).trim();
    const hintStorageKey = `chatbot_hint_hidden_${userKey || "guest"}`;
    const normalizeLocale = (value) =>
        String(value || "")
            .trim()
            .toLowerCase()
            .startsWith("zh")
            ? "zh"
            : "en";
    let activeLocale = normalizeLocale(panel.dataset.locale || document.documentElement.lang || "en");
    const getUiText = (key, locale = activeLocale) =>
        UI_TEXT[normalizeLocale(locale)]?.[key] || UI_TEXT.en[key] || "";
    const detectLocaleFromText = (text, fallbackLocale = activeLocale) => {
        const normalized = String(text || "").trim();
        if (!normalized) {
            return normalizeLocale(fallbackLocale);
        }
        if (CJK_CHAR_RE.test(normalized)) {
            return "zh";
        }
        if (LATIN_CHAR_RE.test(normalized)) {
            return "en";
        }
        return normalizeLocale(fallbackLocale);
    };
    const detectLocaleFromQuickQuestions = (quickQuestions, fallbackLocale = activeLocale) => {
        if (!Array.isArray(quickQuestions)) {
            return normalizeLocale(fallbackLocale);
        }
        for (const item of quickQuestions) {
            if (typeof item !== "string") {
                continue;
            }
            const text = item.trim();
            if (!text) {
                continue;
            }
            return detectLocaleFromText(text, fallbackLocale);
        }
        return normalizeLocale(fallbackLocale);
    };

    let hintDismissedForSession = false;
    let statusAnimationTimer = null;
    let statusAnimationFrame = 0;
    let clearDoneTimer = null;

    const getCsrfToken = () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return (meta?.getAttribute("content") || "").trim();
    };

    const getHintHiddenPreference = () => {
        try {
            return window.localStorage.getItem(hintStorageKey) === "1";
        } catch (_error) {
            return false;
        }
    };

    const saveHintHiddenPreference = () => {
        try {
            window.localStorage.setItem(hintStorageKey, "1");
        } catch (_error) {
            // Ignore storage failures (private mode / blocked storage).
        }
    };

    const stopStatusAnimation = () => {
        if (statusAnimationTimer) {
            window.clearInterval(statusAnimationTimer);
            statusAnimationTimer = null;
        }
    };

    const startStatusAnimation = (textKey, locale = activeLocale) => {
        const baseText = getUiText(textKey, locale);
        if (!baseText) {
            return;
        }
        if (clearDoneTimer) {
            window.clearTimeout(clearDoneTimer);
            clearDoneTimer = null;
        }
        stopStatusAnimation();
        if (prefersReducedMotion) {
            statusEl.textContent = `${baseText}...`;
            return;
        }
        const frames = [baseText, `${baseText}.`, `${baseText}..`, `${baseText}...`];
        statusAnimationFrame = 0;
        statusEl.textContent = frames[0];
        statusAnimationTimer = window.setInterval(() => {
            statusAnimationFrame = (statusAnimationFrame + 1) % frames.length;
            statusEl.textContent = frames[statusAnimationFrame];
        }, 360);
    };

    const setDoneStatus = (locale = activeLocale) => {
        stopStatusAnimation();
        statusEl.textContent = getUiText("done", locale);
        if (clearDoneTimer) {
            window.clearTimeout(clearDoneTimer);
        }
        clearDoneTimer = window.setTimeout(() => {
            if (!sendBtn || !sendBtn.disabled) {
                statusEl.textContent = "";
            }
        }, 1400);
    };

    const hideHint = () => {
        if (!hint) {
            return;
        }
        hint.classList.add("hidden");
        hint.setAttribute("aria-hidden", "true");
    };

    const showHintIfAllowed = () => {
        if (!hint) {
            return;
        }
        if (hintDismissedForSession || getHintHiddenPreference()) {
            hideHint();
            return;
        }
        if (!panel.classList.contains("hidden")) {
            hideHint();
            return;
        }

        hint.classList.remove("hidden");
        hint.setAttribute("aria-hidden", "false");
    };

    const openPanel = () => {
        panel.classList.remove("hidden");
        backdrop.classList.remove("hidden");
        launcher.setAttribute("aria-expanded", "true");
        hideHint();

        window.setTimeout(() => {
            if (isAuthenticated && input) {
                input.focus();
                return;
            }
            if (loginLink) {
                loginLink.focus();
            }
        }, 80);
    };

    const closePanel = () => {
        panel.classList.add("hidden");
        backdrop.classList.add("hidden");
        launcher.setAttribute("aria-expanded", "false");
        launcher.focus();
        window.setTimeout(showHintIfAllowed, 120);
    };

    const escapeHtml = (text) => {
        const raw = String(text ?? "");
        return raw
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    };

    const renderAssistantMarkdown = (text) => {
        let html = escapeHtml(text);

        html = html.replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-ntu-blue underline underline-offset-2">$1</a>'
        );
        html = html.replace(
            /`([^`\n]+)`/g,
            '<code class="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.9em] text-slate-800">$1</code>'
        );
        html = html.replace(/\*\*([^*\n][^*\n]*?)\*\*/g, "<strong>$1</strong>");
        html = html.replace(/\*\*/g, "");

        const blocks = html
            .split(/\n{2,}/)
            .map((block) => block.trim())
            .filter(Boolean)
            .map((block) => `<p class="mb-2 last:mb-0">${block.replace(/\n/g, "<br>")}</p>`);

        if (blocks.length === 0) {
            return "<p></p>";
        }
        return blocks.join("");
    };

    const setStarVisualState = (starButtons, selectedRating) => {
        starButtons.forEach((button) => {
            const value = Number(button.dataset.rating || "0");
            const isSelected = selectedRating > 0 && value <= selectedRating;
            button.classList.toggle("text-amber-500", isSelected);
            button.classList.toggle("text-slate-300", !isSelected);
        });
    };

    const submitFeedback = async ({
        conversationId,
        rating,
        comment,
        starButtons,
        helperText,
        commentInput,
        locale = activeLocale,
    }) => {
        const uiLocale = normalizeLocale(locale);
        const csrfToken = getCsrfToken();
        if (!csrfToken) {
            helperText.textContent = getUiText("missingCsrf", uiLocale);
            return;
        }

        starButtons.forEach((button) => {
            button.disabled = true;
        });
        if (commentInput) {
            commentInput.disabled = true;
        }
        helperText.textContent = getUiText("feedbackSubmitting", uiLocale);

        try {
            const response = await fetch("/api/chat/feedback", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                body: JSON.stringify({
                    conversation_id: conversationId,
                    rating,
                    comment,
                }),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.error || `Request failed (${response.status})`);
            }

            setStarVisualState(starButtons, rating);
            helperText.className = "mt-1 text-[11px] text-green-700";
            helperText.textContent = getUiText("feedbackThanks", uiLocale);
        } catch (error) {
            helperText.className = "mt-1 text-[11px] text-red-600";
            helperText.textContent = error?.message || getUiText("feedbackFailed", uiLocale);
            starButtons.forEach((button) => {
                button.disabled = false;
            });
            if (commentInput) {
                commentInput.disabled = false;
            }
        }
    };

    const appendFeedbackWidget = ({ bubble, conversationId, promptText, locale = activeLocale }) => {
        if (!conversationId) {
            return;
        }
        const uiLocale = normalizeLocale(locale);

        const feedbackWrap = document.createElement("div");
        feedbackWrap.className = "mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2";

        const title = document.createElement("p");
        title.className = "text-xs font-semibold text-amber-900";
        title.textContent = promptText || getUiText("feedbackPrompt", uiLocale);
        feedbackWrap.appendChild(title);

        const commentInput = document.createElement("textarea");
        commentInput.rows = 2;
        commentInput.maxLength = 500;
        commentInput.placeholder = getUiText("feedbackPlaceholder", uiLocale);
        commentInput.className =
            "mt-2 w-full resize-none rounded-lg border border-amber-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:outline-none focus:ring-2 focus:ring-amber-300";
        feedbackWrap.appendChild(commentInput);

        const starsWrap = document.createElement("div");
        starsWrap.className = "mt-2 flex items-center gap-1";
        const starButtons = [];
        let selectedRating = 0;

        for (let value = 1; value <= 5; value += 1) {
            const starBtn = document.createElement("button");
            starBtn.type = "button";
            starBtn.dataset.rating = String(value);
            starBtn.setAttribute("aria-label", `Rate ${value} star${value > 1 ? "s" : ""}`);
            starBtn.className =
                "inline-flex h-11 w-11 items-center justify-center rounded-lg text-2xl text-slate-300 transition focus:outline-none focus:ring-2 focus:ring-amber-300 disabled:cursor-not-allowed disabled:opacity-70";
            starBtn.innerHTML = "&#9733;";
            starsWrap.appendChild(starBtn);
            starButtons.push(starBtn);
        }

        const helperText = document.createElement("p");
        helperText.className = "mt-1 text-[11px] text-amber-700";
        helperText.textContent = getUiText("feedbackTapToRate", uiLocale);

        const restoreSelectedVisualState = () => {
            setStarVisualState(starButtons, selectedRating);
        };

        starsWrap.addEventListener("mouseleave", restoreSelectedVisualState);

        starButtons.forEach((starBtn) => {
            starBtn.addEventListener("mouseenter", () => {
                const hovered = Number(starBtn.dataset.rating || "0");
                setStarVisualState(starButtons, hovered);
            });

            starBtn.addEventListener("focus", () => {
                const focused = Number(starBtn.dataset.rating || "0");
                setStarVisualState(starButtons, focused);
            });

            starBtn.addEventListener("click", () => {
                const rating = Number(starBtn.dataset.rating || "0");
                if (!rating) {
                    return;
                }
                selectedRating = rating;
                setStarVisualState(starButtons, selectedRating);
                submitFeedback({
                    conversationId,
                    rating,
                    comment: commentInput.value.trim(),
                    starButtons,
                    helperText,
                    commentInput,
                    locale: uiLocale,
                });
            });
        });

        feedbackWrap.appendChild(starsWrap);
        feedbackWrap.appendChild(helperText);
        bubble.appendChild(feedbackWrap);
    };

    const appendQuickQuestions = ({ bubble, quickQuestions, locale = activeLocale }) => {
        if (!Array.isArray(quickQuestions) || quickQuestions.length === 0) {
            return;
        }
        const uiLocale = normalizeLocale(locale);

        const wrap = document.createElement("div");
        wrap.className = "mt-3 border-t border-slate-200/80 pt-2.5";
        wrap.setAttribute("data-chatbot-quick-questions", "1");

        const title = document.createElement("p");
        title.className = "mb-2 text-[11px] font-semibold text-slate-500";
        title.textContent = getUiText("quickQuestionsTitle", uiLocale);
        wrap.appendChild(title);

        const list = document.createElement("div");
        list.className = "flex flex-wrap gap-2";

        quickQuestions.forEach((question) => {
            if (typeof question !== "string") {
                return;
            }
            const text = question.trim();
            if (!text) {
                return;
            }

            const btn = document.createElement("button");
            btn.type = "button";
            btn.className =
                "inline-flex min-h-[36px] max-w-full items-center rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-left text-xs text-slate-700 shadow-sm transition-all duration-200 hover:border-ntu-blue/40 hover:bg-white hover:text-ntu-blue focus:outline-none focus:ring-2 focus:ring-ntu-blue/30";
            btn.textContent = text;
            btn.addEventListener("click", () => {
                if (!isAuthenticated || !input || !sendBtn || sendBtn.disabled) {
                    return;
                }
                input.value = text;
                ask();
            });
            list.appendChild(btn);
        });

        if (list.childElementCount > 0) {
            wrap.appendChild(list);
            bubble.appendChild(wrap);
        }
    };

    const clearQuickQuestionPrompts = () => {
        thread
            .querySelectorAll("[data-chatbot-quick-questions='1']")
            .forEach((node) => node.remove());
    };

    const appendMessage = ({ role, text, feedback = null, quickQuestions = [], locale = activeLocale }) => {
        const isUser = role === "user";

        const wrapper = document.createElement("div");
        wrapper.className = isUser ? "flex justify-end" : "flex justify-start";

        const bubble = document.createElement("div");
        bubble.className = isUser
            ? "max-w-[84%] rounded-2xl rounded-br-md border border-blue-800/70 bg-gradient-to-br from-ntu-blue to-blue-800 px-3.5 py-2.5 text-sm text-white shadow-[0_10px_22px_-14px_rgba(30,64,175,0.8)]"
            : "max-w-[90%] rounded-2xl rounded-bl-md border border-slate-200 bg-gradient-to-b from-white to-slate-50 px-3.5 py-2.5 text-sm text-slate-700 shadow-[0_12px_24px_-16px_rgba(15,23,42,0.45)]";

        const textNode = document.createElement("div");
        textNode.className = "break-words leading-relaxed";
        if (!isUser) {
            textNode.innerHTML = renderAssistantMarkdown(text);
        } else {
            textNode.classList.add("whitespace-pre-wrap");
            textNode.textContent = text;
        }
        bubble.appendChild(textNode);

        if (!isUser && feedback && feedback.required) {
            appendFeedbackWidget({
                bubble,
                conversationId: feedback.conversationId,
                promptText: feedback.prompt,
                locale,
            });
        }

        if (!isUser) {
            appendQuickQuestions({
                bubble,
                quickQuestions,
                locale,
            });
        }

        wrapper.appendChild(bubble);
        thread.appendChild(wrapper);
        thread.scrollTop = thread.scrollHeight;
        return { wrapper, bubble, textNode };
    };

    const renderAssistantThinkingDraft = (locale = activeLocale) => {
        const label = escapeHtml(getUiText("thinkingLabel", locale));
        const animatedClass = prefersReducedMotion ? "" : " animate-bounce motion-reduce:animate-none";
        return (
            '<div class="mb-0 inline-flex items-center gap-2 text-slate-400">' +
            `<span class="text-xs font-medium">${label}</span>` +
            '<span class="inline-flex items-center gap-1" aria-hidden="true">' +
            `<span class="h-1.5 w-1.5 rounded-full bg-slate-400${animatedClass}" style="animation-delay:0ms"></span>` +
            `<span class="h-1.5 w-1.5 rounded-full bg-slate-400${animatedClass}" style="animation-delay:120ms"></span>` +
            `<span class="h-1.5 w-1.5 rounded-full bg-slate-400${animatedClass}" style="animation-delay:240ms"></span>` +
            "</span>" +
            "</div>"
        );
    };

    const appendAssistantDraft = (locale = activeLocale) => {
        const { wrapper, bubble, textNode } = appendMessage({
            role: "assistant",
            text: "",
            locale,
        });
        textNode.innerHTML = renderAssistantThinkingDraft(locale);
        return { wrapper, bubble, textNode };
    };

    const updateAssistantDraft = (draft, text) => {
        if (!draft || !draft.textNode) {
            return;
        }
        draft.textNode.innerHTML = renderAssistantMarkdown(text || "");
        thread.scrollTop = thread.scrollHeight;
    };

    const setLoading = (isLoading) => {
        if (!sendBtn || !input) {
            return;
        }
        sendBtn.disabled = isLoading;
        input.disabled = isLoading;
        sendBtn.textContent = isLoading ? getUiText("sending") : getUiText("send");
        if (isLoading) {
            startStatusAnimation("assistantThinking");
            return;
        }
        stopStatusAnimation();
    };

    const ask = async () => {
        if (!isAuthenticated) {
            statusEl.textContent = getUiText("loginRequired");
            return;
        }
        if (!input || !sendBtn) {
            statusEl.textContent = getUiText("chatUnavailable");
            return;
        }

        const message = input.value.trim();
        if (!message) {
            statusEl.textContent = getUiText("enterQuestion");
            return;
        }
        activeLocale = detectLocaleFromText(message, activeLocale);

        const csrfToken = getCsrfToken();
        if (!csrfToken) {
            statusEl.textContent = getUiText("missingCsrf");
            return;
        }

        openPanel();
        clearQuickQuestionPrompts();
        appendMessage({ role: "user", text: message });
        input.value = "";
        setLoading(true);
        const assistantDraft = appendAssistantDraft(activeLocale);

        try {
            const response = await fetch("/api/chat/stream", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                body: JSON.stringify({ message }),
            });

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                const errorMsg = data?.error || `Request failed (${response.status})`;
                updateAssistantDraft(assistantDraft, errorMsg);
                stopStatusAnimation();
                statusEl.textContent = "";
                return;
            }

            if (!response.body) {
                updateAssistantDraft(assistantDraft, getUiText("streamUnavailable"));
                stopStatusAnimation();
                statusEl.textContent = "";
                return;
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";
            let replyText = "";
            let finalPayload = null;
            let streamLocale = activeLocale;
            let sawFirstDelta = false;
            startStatusAnimation("assistantThinking", streamLocale);

            const processLine = (line) => {
                if (!line) {
                    return;
                }
                let payload = null;
                try {
                    payload = JSON.parse(line);
                } catch (_error) {
                    return;
                }
                if (!payload || typeof payload !== "object") {
                    return;
                }
                if (payload.type === "status") {
                    const stage = String(payload.stage || "").toLowerCase();
                    if (stage === "typing") {
                        startStatusAnimation("assistantTyping", streamLocale);
                    } else {
                        startStatusAnimation("assistantThinking", streamLocale);
                    }
                    return;
                }
                if (payload.type === "heartbeat") {
                    return;
                }
                if (payload.type === "delta" && typeof payload.delta === "string") {
                    if (!sawFirstDelta) {
                        sawFirstDelta = true;
                        startStatusAnimation("assistantTyping", streamLocale);
                    }
                    replyText += payload.delta;
                    streamLocale = detectLocaleFromText(replyText, streamLocale);
                    updateAssistantDraft(assistantDraft, replyText);
                    return;
                }
                if (payload.type === "final") {
                    finalPayload = payload;
                    if (typeof payload.reply === "string" && payload.reply.trim()) {
                        replyText = payload.reply.trim();
                        streamLocale = detectLocaleFromText(replyText, streamLocale);
                        updateAssistantDraft(assistantDraft, replyText);
                    }
                    return;
                }
                if (payload.type === "error") {
                    throw new Error(payload.error || getUiText("streamingFailed", streamLocale));
                }
            };

            while (true) {
                const { value, done } = await reader.read();
                if (done) {
                    break;
                }
                buffer += decoder.decode(value, { stream: true });
                while (true) {
                    const newlineIndex = buffer.indexOf("\n");
                    if (newlineIndex < 0) {
                        break;
                    }
                    const line = buffer.slice(0, newlineIndex).trim();
                    buffer = buffer.slice(newlineIndex + 1);
                    processLine(line);
                }
            }

            const trailing = buffer.trim();
            if (trailing) {
                processLine(trailing);
            }

            const finalReply = (replyText || "").trim() || getUiText("noReply", streamLocale);
            updateAssistantDraft(assistantDraft, finalReply);

            const feedbackRequired = Boolean(finalPayload?.feedback_required);
            const conversationId =
                typeof finalPayload?.conversation_id === "string" ? finalPayload.conversation_id : "";
            const feedbackPrompt =
                typeof finalPayload?.feedback_prompt === "string" ? finalPayload.feedback_prompt : "";
            const quickQuestions = Array.isArray(finalPayload?.quick_questions)
                ? finalPayload.quick_questions
                : [];
            streamLocale = detectLocaleFromQuickQuestions(
                quickQuestions,
                detectLocaleFromText(finalReply, streamLocale)
            );
            activeLocale = streamLocale;

            if (feedbackRequired) {
                appendFeedbackWidget({
                    bubble: assistantDraft.bubble,
                    conversationId,
                    promptText: feedbackPrompt,
                    locale: streamLocale,
                });
            }
            appendQuickQuestions({
                bubble: assistantDraft.bubble,
                quickQuestions,
                locale: streamLocale,
            });
            setDoneStatus(streamLocale);
        } catch (error) {
            updateAssistantDraft(
                assistantDraft,
                error?.message || getUiText("requestFailed", activeLocale)
            );
            stopStatusAnimation();
            statusEl.textContent = "";
        } finally {
            setLoading(false);
            if (input) {
                input.focus();
            }
        }
    };

    launcher.addEventListener("click", () => {
        if (panel.classList.contains("hidden")) {
            openPanel();
            if (!isAuthenticated) {
                statusEl.textContent = getUiText("loginRequired");
            }
        } else {
            closePanel();
        }
    });

    closeBtn.addEventListener("click", closePanel);
    backdrop.addEventListener("click", closePanel);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !panel.classList.contains("hidden")) {
            closePanel();
        }
    });

    if (sendBtn) {
        sendBtn.addEventListener("click", ask);
    }

    if (input) {
        input.addEventListener("keydown", (event) => {
            if (event.key !== "Enter") {
                return;
            }
            if (event.isComposing) {
                return;
            }
            if (event.ctrlKey || event.metaKey) {
                return;
            }
            event.preventDefault();
            ask();
        });
    }

    if (hintDismissBtn) {
        hintDismissBtn.addEventListener("click", () => {
            hintDismissedForSession = true;
            hideHint();
        });
    }

    if (hintNeverCheckbox) {
        if (getHintHiddenPreference()) {
            hintNeverCheckbox.checked = true;
        }

        hintNeverCheckbox.addEventListener("change", () => {
            if (!hintNeverCheckbox.checked) {
                return;
            }
            saveHintHiddenPreference();
            hintDismissedForSession = true;
            hideHint();
        });
    }

    window.setTimeout(showHintIfAllowed, 700);
})();
