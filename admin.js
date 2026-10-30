// ==================================================
// EGER AI ADMIN DASHBOARD
// ==================================================

const API_URL = "https://eger-ai.onrender.com";


// ==================================================
// GET ADMIN PASSWORD USING NORMAL PROMPT
// ==================================================

function getAdminPassword() {
    const password = prompt(
        "Enter your Eger AI administrator password:"
    );

    if (password === null || password.length === 0) {
        return null;
    }

    return password;
}


// ==================================================
// READ SERVER RESPONSE SAFELY
// ==================================================

async function readResponse(response) {
    const responseText = await response.text();

    let data;

    try {
        data = JSON.parse(responseText);
    } catch {
        data = {
            error: responseText || "Unexpected server response."
        };
    }

    if (!response.ok) {
        throw new Error(
            data.error ||
            data.message ||
            `Request failed with status ${response.status}.`
        );
    }

    return data;
}


// ==================================================
// 1. MANUAL KNOWLEDGE FORM
// ==================================================

const knowledgeForm = document.getElementById("knowledgeForm");

const questionInput = document.getElementById("question");

const keywordsInput = document.getElementById("keywords");

const answerInput = document.getElementById("answer");

const addButton = document.getElementById("addButton");

const knowledgeMessage = document.getElementById("knowledgeMessage");


if (knowledgeForm) {
    knowledgeForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const question = questionInput.value.trim();
        const keywords = keywordsInput.value.trim();
        const answer = answerInput.value.trim();

        // Validate form fields.

        if (!question || !keywords || !answer) {
            knowledgeMessage.textContent =
                "Please fill in all fields.";

            return;
        }

        // Ask for the administrator password.

        const adminPassword = getAdminPassword();

        if (adminPassword === null || adminPassword.length === 0) {
            knowledgeMessage.textContent =
                "Action cancelled.";

            return;
        }

        addButton.disabled = true;
        addButton.textContent = "ADDING KNOWLEDGE...";

        knowledgeMessage.textContent =
            "Saving information...";

        try {
            const response = await fetch(
                `${API_URL}/add`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type": "application/json",
                        "Authorization": `Bearer ${adminPassword}`
                    },

                    body: JSON.stringify({
                        question,
                        keywords,
                        answer
                    })
                }
            );

            const data = await readResponse(response);

            knowledgeMessage.textContent =
                data.message ||
                "Knowledge added successfully!";

            knowledgeForm.reset();

        } catch (error) {
            console.error(
                "Knowledge submission error:",
                error
            );

            knowledgeMessage.textContent =
                "Failed to add knowledge: " +
                error.message;

        } finally {
            addButton.disabled = false;
            addButton.textContent = "ADD KNOWLEDGE";
        }
    });
}


// ==================================================
// 2. DOCUMENT UPLOAD FORM
// ==================================================

const uploadForm = document.getElementById("uploadForm");

const titleInput = document.getElementById("title");

const categoryInput = document.getElementById("category");

const documentInput = document.getElementById("document");

const uploadButton = document.getElementById("uploadButton");

const uploadMessage = document.getElementById("uploadMessage");


if (uploadForm) {
    uploadForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const title = titleInput.value.trim();
        const category = categoryInput.value;
        const file = documentInput.files[0];

        // Validate the form.

        if (!title || !category || !file) {
            uploadMessage.textContent =
                "Please complete all fields.";

            return;
        }

        // Check file extension.

        const allowedExtensions = [
            ".pdf",
            ".docx",
            ".txt"
        ];

        const fileName = file.name.toLowerCase();

        const validExtension = allowedExtensions.some(
            extension => fileName.endsWith(extension)
        );

        if (!validExtension) {
            uploadMessage.textContent =
                "Please select a PDF, DOCX, or TXT document.";

            return;
        }

        // Enforce a 10 MB client-side size limit.

        const MAX_FILE_SIZE = 10 * 1024 * 1024;

        if (file.size > MAX_FILE_SIZE) {
            uploadMessage.textContent =
                "The file is too large. Maximum size is 10 MB.";

            return;
        }

        // Ask for the administrator password.

        const adminPassword = getAdminPassword();

        if (adminPassword === null || adminPassword.length === 0) {
            uploadMessage.textContent =
                "Upload cancelled.";

            return;
        }

        // Prepare the multipart form data.

        const formData = new FormData();

        formData.append("title", title);
        formData.append("category", category);
        formData.append("document", file);

        uploadButton.disabled = true;
        uploadButton.textContent = "UPLOADING...";

        uploadMessage.textContent =
            "Uploading and processing document...";

        try {
            const response = await fetch(
                `${API_URL}/upload`,
                {
                    method: "POST",

                    headers: {
                        "Authorization": `Bearer ${adminPassword}`
                    },

                    body: formData
                }
            );

            const data = await readResponse(response);

            // Support both the new and previous backend formats.

            const characterCount =
                data.characters ??
                data.characters_extracted ??
                data.character_count ??
                0;

            uploadMessage.textContent =
                `${data.message || "Document uploaded successfully!"} ` +
                `Extracted ${characterCount} characters.`;

            uploadForm.reset();

        } catch (error) {
            console.error(
                "Document upload error:",
                error
            );

            uploadMessage.textContent =
                "Upload failed: " +
                error.message;

        } finally {
            uploadButton.disabled = false;
            uploadButton.textContent = "UPLOAD DOCUMENT";
        }
    });
}