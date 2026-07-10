document.addEventListener("DOMContentLoaded", () => {
    // ---------------------------------------------------------
    // DOM Elements
    // ---------------------------------------------------------
    const body = document.body;
    const sidebar = document.getElementById("app-sidebar");
    const sidebarToggle = document.getElementById("sidebar-toggle");
    const rightPanel = document.getElementById("app-right-panel");
    const rightPanelToggle = document.getElementById("right-panel-toggle");
    const themeToggle = document.getElementById("theme-toggle");
    
    const searchForm = document.getElementById("search-form");
    const searchCardContainer = document.getElementById("search-card-container");
    const platformSelect = document.getElementById("platform-select");
    const queryInput = document.getElementById("query-input");
    
    const loadingCard = document.getElementById("loading-card");
    const loadingProgressBar = document.getElementById("loading-progress-bar");
    const loadingStatus = document.getElementById("loading-status");
    
    const resultsSection = document.getElementById("results-section");
    const resultsContainer = document.getElementById("results-container");
    const resetSearchBtn = document.getElementById("reset-search-btn");
    
    const chatForm = document.getElementById("chat-form");
    const chatInput = document.getElementById("chat-input");
    const chatMessages = document.getElementById("chat-messages");
    
    const statTotal = document.getElementById("stat-total");
    const statBookmarks = document.getElementById("stat-bookmarks");
    const statFavorite = document.getElementById("stat-favorite");
    const recentSearchesList = document.getElementById("recent-searches-list");
    const historyBadge = document.getElementById("history-badge");

    // ---------------------------------------------------------
    // State Variables
    // ---------------------------------------------------------
    let totalSearchesCount = parseInt(localStorage.getItem("total_searches") || "0");
    let bookmarksCount = parseInt(localStorage.getItem("bookmarks_count") || "0");
    let searchHistory = JSON.parse(localStorage.getItem("search_history") || "[]");
    let bookmarksList = JSON.parse(localStorage.getItem("bookmarks_list") || "[]");
    let activeResearchData = null;

    // Initialize stats display
    updateStatsUI();
    renderRecentSearches();

    // Initialize Lucide Icons
    if (typeof lucide !== "undefined") {
        lucide.createIcons();
    }

    // ---------------------------------------------------------
    // Left Sidebar Collapsible Panel
    // ---------------------------------------------------------
    sidebarToggle.addEventListener("click", () => {
        if (window.innerWidth <= 768) {
            sidebar.classList.toggle("active");
            sidebar.classList.remove("collapsed");
        } else {
            sidebar.classList.toggle("collapsed");
        }
    });

    // ---------------------------------------------------------
    // Right Stats Panel Collapsible
    // ---------------------------------------------------------
    rightPanelToggle.addEventListener("click", () => {
        rightPanel.classList.toggle("collapsed");
    });

    // Handle screen resize behavior
    window.addEventListener("resize", () => {
        if (window.innerWidth <= 768) {
            sidebar.classList.remove("collapsed");
        } else {
            sidebar.classList.remove("active");
        }
    });

    // Sidebar navigation active state toggle
    document.querySelectorAll(".sidebar-item").forEach(item => {
        item.addEventListener("click", (e) => {
            if (item.id === "sidebar-toggle" || item.id === "right-panel-toggle") return;
            document.querySelectorAll(".sidebar-item").forEach(i => i.classList.remove("active"));
            item.classList.add("active");
        });
    });

    // ---------------------------------------------------------
    // Theme Toggle Handler
    // ---------------------------------------------------------
    const savedTheme = localStorage.getItem("theme") || "dark";
    if (savedTheme === "light") {
        body.classList.remove("dark-theme");
        body.classList.add("light-theme");
    }

    themeToggle.addEventListener("click", () => {
        if (body.classList.contains("dark-theme")) {
            body.classList.remove("dark-theme");
            body.classList.add("light-theme");
            localStorage.setItem("theme", "light");
        } else {
            body.classList.remove("light-theme");
            body.classList.add("dark-theme");
            localStorage.setItem("theme", "dark");
        }
    });

    // ---------------------------------------------------------
    // Button Ripple Effect
    // ---------------------------------------------------------
    document.addEventListener("click", (e) => {
        const rippleBtn = e.target.closest(".btn-ripple");
        if (rippleBtn) {
            const ripple = document.createElement("span");
            ripple.classList.add("ripple-effect");
            
            const rect = rippleBtn.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            ripple.style.width = ripple.style.height = `${size}px`;
            
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;
            ripple.style.left = `${x}px`;
            ripple.style.top = `${y}px`;
            
            rippleBtn.appendChild(ripple);
            setTimeout(() => ripple.remove(), 600);
        }
    });

    // ---------------------------------------------------------
    // Research Form Submission
    // ---------------------------------------------------------
    searchForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const platform = platformSelect.value;
        const query = queryInput.value.trim();
        
        if (!query) return;

        // Toggle UI states
        searchCardContainer.classList.add("hidden");
        loadingCard.classList.remove("hidden");
        resultsSection.classList.add("hidden");
        
        // Reset loading step styles
        document.querySelectorAll(".loading-step").forEach(step => {
            step.classList.remove("active", "completed");
        });
        loadingProgressBar.style.width = "0%";
        
        let loadingFinished = false;

        // Start step-by-step progress loading animation
        const steps = [
            { id: "step-1", percent: 20, msg: "Connecting to agent environment..." },
            { id: "step-2", percent: 40, msg: "Searching feeds and scrapers..." },
            { id: "step-3", percent: 60, msg: "Collecting data points and metrics..." },
            { id: "step-4", percent: 80, msg: "Filtering database entries with ChromaDB..." },
            { id: "step-5", percent: 100, msg: "Synthesizing insights and generating summary..." }
        ];

        let currentStepIndex = 0;

        function runNextStep() {
            if (currentStepIndex >= steps.length || loadingFinished) return;
            
            const step = steps[currentStepIndex];
            const stepEl = document.getElementById(step.id);
            
            // Mark previous steps as completed
            for (let i = 0; i < currentStepIndex; i++) {
                const prevStep = document.getElementById(steps[i].id);
                prevStep.classList.remove("active");
                prevStep.classList.add("completed");
            }

            stepEl.classList.add("active");
            loadingStatus.textContent = step.msg;
            loadingProgressBar.style.width = `${step.percent}%`;
            
            currentStepIndex++;
            
            // Trigger next step after artificial delay to show off beautiful transitions
            setTimeout(runNextStep, 1500);
        }

        // Run loading steps animation
        runNextStep();

        try {
            // Trigger fetch request
            const response = await fetch("/research", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ platform, query })
            });

            if (!response.ok) {
                throw new Error("Research request failed");
            }

            const data = await response.json();
            activeResearchData = data;
            
            // Save query in search history
            saveSearchToHistory(platform, query);
            totalSearchesCount++;
            localStorage.setItem("total_searches", totalSearchesCount.toString());
            
            // Short delay to ensure steps look organic
            setTimeout(() => {
                loadingFinished = true;
                
                // Complete all steps in UI
                steps.forEach(s => {
                    const el = document.getElementById(s.id);
                    el.classList.remove("active");
                    el.classList.add("completed");
                });
                loadingProgressBar.style.width = "100%";
                
                setTimeout(() => {
                    // Transition to result card
                    loadingCard.classList.add("hidden");
                    resultsSection.classList.remove("hidden");
                    renderResultCard(data);
                    
                    // Reset follow-up chat
                    chatMessages.innerHTML = `
                        <div class="chat-message assistant">
                            <div class="chat-message-avatar"><i data-lucide="sparkles"></i></div>
                            <div class="chat-message-bubble">
                                I have compiled the initial intelligence on <strong>${data.title}</strong>. What specific details would you like to drill into further?
                            </div>
                        </div>
                    `;
                    if (typeof lucide !== "undefined") lucide.createIcons();
                    updateStatsUI();
                    renderRecentSearches();
                }, 800);
            }, 3000);

        } catch (error) {
            console.error(error);
            loadingFinished = true;
            loadingStatus.innerHTML = `<span style="color: #ef4444;">Error: Failed to process research. Please retry.</span>`;
            setTimeout(() => {
                loadingCard.classList.add("hidden");
                searchCardContainer.classList.remove("hidden");
            }, 3000);
        }
    });

    // ---------------------------------------------------------
    // Render Results Card Dynamically
    // ---------------------------------------------------------
    function renderResultCard(data) {
        resultsContainer.innerHTML = ""; // Clear existing

        const card = document.createElement("div");
        card.className = "glass-card result-card";

        const platformClass = data.platform.toLowerCase().replace(" ", "-");
        const platformIconMap = {
            "youtube": "youtube",
            "instagram": "instagram",
            "linkedin": "linkedin",
            "pdf documents": "file-text"
        };
        const iconName = platformIconMap[data.platform.toLowerCase()] || "link-2";

        // Check if bookmark already exists
        const isBookmarked = bookmarksList.some(item => item.title === data.title);
        const bookmarkBtnClass = isBookmarked ? "btn-primary" : "btn-secondary";
        const bookmarkText = isBookmarked ? "Bookmarked" : "Bookmark";
        const bookmarkIcon = isBookmarked ? "check" : "bookmark";

        card.innerHTML = `
            <div class="result-header">
                <h3 class="result-title">${escapeHtml(data.title)}</h3>
                <span class="platform-badge ${platformClass}">
                    <i data-lucide="${iconName}"></i>
                    ${escapeHtml(data.platform)}
                </span>
            </div>
            <div class="result-summary">${formatResearchReport(data.summary)}</div>
            <a href="${data.source}" target="_blank" class="result-source">
                <i data-lucide="external-link"></i>
                Source URL Link
            </a>
            <div class="card-actions">
                <a href="${data.source}" target="_blank" class="btn btn-primary btn-ripple">
                    <i data-lucide="external-link"></i>
                    <span>Open Source</span>
                </a>
                <button class="btn btn-secondary btn-ripple" id="action-copy">
                    <i data-lucide="copy"></i>
                    <span>Copy Summary</span>
                </button>
                <button class="btn ${bookmarkBtnClass} btn-ripple" id="action-bookmark">
                    <i data-lucide="${bookmarkIcon}"></i>
                    <span>${bookmarkText}</span>
                </button>
                <button class="btn btn-secondary btn-ripple" id="action-download">
                    <i data-lucide="download"></i>
                    <span>Download Report</span>
                </button>
            </div>
        `;

        resultsContainer.appendChild(card);
        if (typeof lucide !== "undefined") lucide.createIcons();

        // ---------------------------------------------------------
        // Result Action Handlers
        // ---------------------------------------------------------
        
        // Copy summary to clipboard
        document.getElementById("action-copy").addEventListener("click", () => {
            navigator.clipboard.writeText(data.summary).then(() => {
                const btn = document.getElementById("action-copy");
                btn.innerHTML = `<i data-lucide="check"></i> <span>Copied!</span>`;
                if (typeof lucide !== "undefined") lucide.createIcons();
                setTimeout(() => {
                    btn.innerHTML = `<i data-lucide="copy"></i> <span>Copy Summary</span>`;
                    if (typeof lucide !== "undefined") lucide.createIcons();
                }, 2000);
            });
        });

        // Bookmark card toggle handler
        document.getElementById("action-bookmark").addEventListener("click", () => {
            const index = bookmarksList.findIndex(item => item.title === data.title);
            const btn = document.getElementById("action-bookmark");
            
            if (index > -1) {
                // Remove bookmark
                bookmarksList.splice(index, 1);
                bookmarksCount = Math.max(0, bookmarksCount - 1);
                btn.className = "btn btn-secondary btn-ripple";
                btn.innerHTML = `<i data-lucide="bookmark"></i> <span>Bookmark</span>`;
            } else {
                // Add bookmark
                bookmarksList.push(data);
                bookmarksCount++;
                btn.className = "btn btn-primary btn-ripple";
                btn.innerHTML = `<i data-lucide="check"></i> <span>Bookmarked</span>`;
            }

            localStorage.setItem("bookmarks_count", bookmarksCount.toString());
            localStorage.setItem("bookmarks_list", JSON.stringify(bookmarksList));
            if (typeof lucide !== "undefined") lucide.createIcons();
            updateStatsUI();
        });

        // Download Report as text file
        document.getElementById("action-download").addEventListener("click", () => {
            const textContent = `Title: ${data.title}\nPlatform: ${data.platform}\nSource: ${data.source}\n\nSummary:\n${data.summary}`;
            const blob = new Blob([textContent], { type: "text/plain" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${data.title.toLowerCase().replace(/[^a-z0-9]+/g, "_")}_report.txt`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });
    }

    // Reset research view button
    resetSearchBtn.addEventListener("click", () => {
        resultsSection.classList.add("hidden");
        searchCardContainer.classList.remove("hidden");
        queryInput.value = "";
        queryInput.focus();
    });

    // ---------------------------------------------------------
    // Follow-up Chat Submit Handler
    // ---------------------------------------------------------
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const userText = chatInput.value.trim();
        if (!userText) return;

        // Append User Message
        appendMessage("user", userText);
        chatInput.value = "";

        // Trigger typing indicator
        const typingId = appendTypingIndicator();

        try {
            const contextText = activeResearchData ? activeResearchData.summary : "";
            const response = await fetch("/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ query: userText, context: contextText })
            });

            if (!response.ok) {
                throw new Error("Chat request failed");
            }

            const data = await response.json();
            removeTypingIndicator(typingId);
            appendMessage("assistant", data.response);

        } catch (error) {
            console.error(error);
            removeTypingIndicator(typingId);
            appendMessage("assistant", "Sorry, I encountered an error trying to process your follow-up question. Please try again.");
        }
    });


    function appendMessage(sender, text) {
        const msg = document.createElement("div");
        msg.className = `chat-message ${sender}`;
        
        const avatarIcon = sender === "user" ? "user" : "sparkles";
        
        msg.innerHTML = `
            <div class="chat-message-avatar"><i data-lucide="${avatarIcon}"></i></div>
            <div class="chat-message-bubble">${escapeHtml(text)}</div>
        `;
        chatMessages.appendChild(msg);
        if (typeof lucide !== "undefined") lucide.createIcons();
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function appendTypingIndicator() {
        const id = "typing-" + Date.now();
        const msg = document.createElement("div");
        msg.className = "chat-message assistant";
        msg.id = id;
        msg.innerHTML = `
            <div class="chat-message-avatar"><i data-lucide="sparkles"></i></div>
            <div class="chat-message-bubble typing-cursor">AI agent is thinking</div>
        `;
        chatMessages.appendChild(msg);
        if (typeof lucide !== "undefined") lucide.createIcons();
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return id;
    }

    function removeTypingIndicator(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    // ---------------------------------------------------------
    // History & LocalStorage Mechanics
    // ---------------------------------------------------------
    function saveSearchToHistory(platform, query) {
        // Keep search history limited to top 10 items
        const item = {
            id: Date.now(),
            platform,
            query,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };
        searchHistory.unshift(item);
        if (searchHistory.length > 10) searchHistory.pop();
        localStorage.setItem("search_history", JSON.stringify(searchHistory));
    }

    function updateStatsUI() {
        statTotal.textContent = totalSearchesCount.toString();
        statBookmarks.textContent = bookmarksCount.toString();
        historyBadge.textContent = searchHistory.length.toString();
        
        // Calculate Favorite platform
        if (searchHistory.length > 0) {
            const counts = {};
            searchHistory.forEach(item => {
                counts[item.platform] = (counts[item.platform] || 0) + 1;
            });
            let favorite = "-";
            let max = 0;
            for (const key in counts) {
                if (counts[key] > max) {
                    max = counts[key];
                    favorite = key;
                }
            }
            statFavorite.textContent = favorite;
        } else {
            statFavorite.textContent = "-";
        }
    }

    function renderRecentSearches() {
        recentSearchesList.innerHTML = "";
        
        if (searchHistory.length === 0) {
            recentSearchesList.innerHTML = `
                <div class="empty-recent-state">
                    <i data-lucide="search-check" class="empty-icon"></i>
                    <p>No recent activity. Launch your first research query!</p>
                </div>
            `;
            if (typeof lucide !== "undefined") lucide.createIcons();
            return;
        }

        searchHistory.forEach(item => {
            const el = document.createElement("div");
            el.className = "recent-item";
            
            const platformClass = item.platform.toLowerCase().replace(" ", "-");
            const platformIconMap = {
                "youtube": "youtube",
                "instagram": "instagram",
                "linkedin": "linkedin",
                "pdf documents": "file-text"
            };
            const iconName = platformIconMap[item.platform.toLowerCase()] || "link-2";

            el.innerHTML = `
                <div class="recent-item-icon ${platformClass === 'pdf-documents' ? 'pdf' : platformClass}">
                    <i data-lucide="${iconName}"></i>
                </div>
                <div class="recent-item-details">
                    <span class="recent-item-query">${escapeHtml(item.query)}</span>
                    <span class="recent-item-time">${item.platform} • ${item.time}</span>
                </div>
            `;

            // Clicking a recent item loads it directly into the search bar
            el.addEventListener("click", () => {
                platformSelect.value = item.platform;
                queryInput.value = item.query;
                queryInput.focus();
                
                // Show homepage if not active
                document.querySelectorAll(".sidebar-item").forEach(i => i.classList.remove("active"));
                document.getElementById("nav-home").classList.add("active");
                searchCardContainer.classList.remove("hidden");
                resultsSection.classList.add("hidden");
                loadingCard.classList.add("hidden");
            });

            recentSearchesList.appendChild(el);
        });

        if (typeof lucide !== "undefined") lucide.createIcons();
    }

    // ---------------------------------------------------------
    // Helper utilities
    // ---------------------------------------------------------
    function escapeHtml(str) {
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function formatResearchReport(text) {
        if (!text) return "";
        
        let lines = text.split("\n");
        let htmlOutput = [];
        let inList = false;
        let inTable = false;
        
        for (let line of lines) {
            let trimmed = line.trim();
            
            // Handle horizontal rule/divider symbols (--- or ===)
            if (/^[-=_*]{3,}$/.test(trimmed)) {
                if (inList) { htmlOutput.push("</ul>"); inList = false; }
                htmlOutput.push('<div class="report-divider"></div>');
                continue;
            }
            
            // Handle Headers (###, ##, #)
            if (trimmed.startsWith("#")) {
                if (inList) { htmlOutput.push("</ul>"); inList = false; }
                let level = 0;
                while (trimmed.startsWith("#")) {
                    level++;
                    trimmed = trimmed.substring(1);
                }
                trimmed = trimmed.trim();
                if (trimmed) {
                    htmlOutput.push(`<h${level + 1} class="report-header report-header-l${level}">${parseInlineMarkdown(trimmed)}</h${level + 1}>`);
                }
                continue;
            }
            
            // Handle List Items (* or - or •)
            if (trimmed.startsWith("* ") || trimmed.startsWith("- ") || trimmed.startsWith("• ")) {
                if (!inList) {
                    htmlOutput.push('<ul class="report-list">');
                    inList = true;
                }
                let itemText = trimmed.replace(/^[\*\-•]\s+/, "");
                htmlOutput.push(`<li>${parseInlineMarkdown(itemText)}</li>`);
                continue;
            }
            
            // Close list if line is not list item
            if (inList && trimmed !== "") {
                htmlOutput.push("</ul>");
                inList = false;
            }
            
            // Handle Table rows
            if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
                if (trimmed.includes("---")) continue; // skip divider row
                
                if (!inTable) {
                    htmlOutput.push('<div class="report-table-wrapper"><table class="report-table">');
                    inTable = true;
                }
                
                let cells = trimmed.split("|").slice(1, -1).map(c => c.trim());
                htmlOutput.push('<tr>');
                for (let cell of cells) {
                    if (cell.startsWith("**") && cell.endsWith("**")) {
                        let cleanCell = cell.replace(/\*\*/g, "");
                        htmlOutput.push(`<th>${parseInlineMarkdown(cleanCell)}</th>`);
                    } else {
                        htmlOutput.push(`<td>${parseInlineMarkdown(cell)}</td>`);
                    }
                }
                htmlOutput.push('</tr>');
                continue;
            }
            
            // Close table if line is not table row
            if (inTable && !trimmed.startsWith("|")) {
                htmlOutput.push("</table></div>");
                inTable = false;
            }
            
            // Handle normal paragraphs
            if (trimmed !== "") {
                htmlOutput.push(`<p class="report-paragraph">${parseInlineMarkdown(trimmed)}</p>`);
            }
        }
        
        if (inList) htmlOutput.push("</ul>");
        if (inTable) htmlOutput.push("</table></div>");
        
        return htmlOutput.join("\n");
    }

    function parseInlineMarkdown(text) {
        // Escape standard HTML first
        let escaped = escapeHtml(text);
        
        // Replace **bold** with <strong>bold</strong>
        escaped = escaped.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
        
        // Replace *italic* or _italic_ with <em>italic</em>
        escaped = escaped.replace(/\*(.*?)\*/g, "<em>$1</em>");
        escaped = escaped.replace(/_(.*?)_/g, "<em>$1</em>");
        
        return escaped;
    }
});
