const hasShortReading = true; // Change to true when needed

// Hide/show the short reading section based on the toggle
document.addEventListener('DOMContentLoaded', function() {
    const shortReadingSection = document.getElementById('shortReading');
    if (shortReadingSection && !hasShortReading) {
        shortReadingSection.style.display = 'none';
    }
});


// Gallery navigation
const galleryImages = [
    'images/meeting-1.jpeg',
	'images/meeting-2.jpeg',
	'images/meeting-3.jpeg',
    // image paths are to be added here
];

const galleryCaptions = [
    'this is a caption that is meant to say stuff',
	'this is another caption meant to say other stuff',
	'Oh look! Another caption that is meant to say more stuff but doesnt.',
    // captions are to be added here
];

let currentImageIndex = 0;

function previousImage() {
    currentImageIndex = (currentImageIndex - 1 + galleryImages.length) % galleryImages.length;
    updateGalleryImage();
}

function nextImage() {
    currentImageIndex = (currentImageIndex + 1) % galleryImages.length;
    updateGalleryImage();
}

function updateGalleryImage() {
    const imageElement = document.querySelector('.gallery-image');
    const captionElement = document.querySelector('.gallery-caption');
    
    if (imageElement && galleryImages[currentImageIndex]) {
        imageElement.src = galleryImages[currentImageIndex];
    }
    if (captionElement && galleryCaptions[currentImageIndex]) {
        captionElement.textContent = galleryCaptions[currentImageIndex];
    }
}

// FAQ ACCORDION
document.addEventListener('DOMContentLoaded', function() {
    const faqQuestions = document.querySelectorAll('.faq-question');
    
    faqQuestions.forEach(question => {
        question.addEventListener('click', function() {
            const faqItem = this.parentElement;
            
            faqItem.classList.toggle('active');
        });
    });
});


// SQUEAK SOUND EASTER EGG
document.addEventListener('DOMContentLoaded', function() {
    const squeakWord = document.getElementById('squeaks');
    
    if (squeakWord) {
        squeakWord.addEventListener('click', function() {
            playSqueak();
        });
    }
});

function playSqueak() {
    const audio = new Audio('assets/squeak.mp3');
    audio.volume = 0.5;
    audio.play().catch(error => {
        console.log('Audio playback failed:', error);
    });
}