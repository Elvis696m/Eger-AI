// ==================================================
// EGER AI ADMIN DASHBOARD
// ==================================================

const API_URL = "https://eger-ai.onrender.com";


// ==================================================
// GET ADMIN PASSWORD
// ==================================================
// ==================================================
// GET ADMIN PASSWORD USING CUSTOM DIALOG
// ==================================================

function getAdminPassword() {
    return new Promise((resolve) => {
        const dialog = document.getElementById("passwordDialog");
        const passwordInput = document.getElementById("adminPasswordInput");
        const confirmButton = document.getElementById("confirmPasswordButton");
        const cancelButton = document.getElementById("cancelPasswordButton");

        if (!dialog || !passwordInput || !confirmButton || !cancelButton) {
            resolve(null);
            return;
        }

        passwordInput.value = "";
        dialog.style.display = "flex";
        passwordInput.focus();

        function cleanup(password) {
            dialog.style.display = "none";

            confirmButton.removeEventListener("click", confirm);
            cancelButton.removeEventListener("click", cancel);
            passwordInput.removeEventListener("keydown", handleEnter);

            resolve(password);
        }

        function confirm() {
            const password = passwordInput.value;

            if (!password) {
                alertMessage("Please enter your administrator password.");
                passwordInput.focus();
                return;
            }

            cleanup(password);
        }

        function cancel() {
            cleanup(null);
        }

        function handleEnter(event) {
            if (event.key === "Enter") {
                event.preventDefault();
                confirm();
            }

            if (event.key === "Escape") {
                cancel();
            }
        }

        confirmButton.addEventListener("click", confirm);
        cancelButton.addEventListener("click", cancel);
        passwordInput.addEventListener("keydown", handleEnter);
    });
}

// Display a message without relying on alert().
function alertMessage(message) {
    const messageElement = document.getElementById("uploadMessage");

    if (messageElement) {
        messageElement.textContent = message;
    }
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

const knowledgeForm = document.getElementById(
    "knowledgeForm"
);

const questionInput = document.getElementById(
    "question"
);

const keywordsInput = document.getElementById(
    "keywords"
);

const answerInput = document.getElementById(
    "answer"
);

const addButton = document.getElementById(
    "addButton"
);

const knowledgeMessage = document.getElementById(
    "knowledgeMessage"
);


if (knowledgeForm) {

    knowledgeForm.addEventListener(
        "submit",
        async function (event) {

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

            if (adminPassword === null) {

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
        }
    );
}


// ==================================================
// 2. DOCUMENT UPLOAD FORM
// ==================================================

const uploadForm = document.getElementById(
    "uploadForm"
);

const titleInput = document.getElementById(
    "title"
);

const categoryInput = document.getElementById(
    "category"
);

const documentInput = document.getElementById(
    "document"
);

const uploadButton = document.getElementById(
    "uploadButton"
);

const uploadMessage = document.getElementById(
    "uploadMessage"
);


if (uploadForm) {

    uploadForm.addEventListener(
        "submit",
        async function (event) {

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

            if (adminPassword === null) {

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


                uploadMessage.textContent =
                    `${data.message} ` +
                    `Extracted ${data.characters_extracted} characters.`;

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
        }
    );
}