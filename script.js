const hasShortReading = true; // Change to true when needed

document.addEventListener('DOMContentLoaded', function() {
    const shortReadingSection = document.getElementById('shortReading');
    if (shortReadingSection && !hasShortReading) {
        shortReadingSection.style.display = 'none';
    }
});

// Gallery navigation
document.addEventListener('DOMContentLoaded', function() {
    const images = document.querySelectorAll('.gallery-image');
    const captionElement = document.querySelector('.gallery-caption');
    const prevBtn = document.querySelector('.gallery-nav-btn.prev');
    const nextBtn = document.querySelector('.gallery-nav-btn.next');
    
    const modal = document.getElementById('galleryModal');
    const modalImage = document.getElementById('modalImage');
    const modalCaption = document.getElementById('modalCaption');
    const modalClose = document.getElementById('modalClose');
    const modalPrev = document.getElementById('modalPrev');
    const modalNext = document.getElementById('modalNext');
    
    let currentImageIndex = 0;
    
    function updateGallery() {
        images.forEach((img, index) => {
            if (index === currentImageIndex) {
                img.classList.add('active');
                
                img.onload = function() {
                    if (img.naturalWidth > img.naturalHeight) {
                        img.classList.add('landscape');
                        img.classList.remove('portrait');
                    } else {
                        img.classList.add('portrait');
                        img.classList.remove('landscape');
                    }
                };
                
                if (img.complete && img.naturalWidth > 0) {
                    if (img.naturalWidth > img.naturalHeight) {
                        img.classList.add('landscape');
                        img.classList.remove('portrait');
                    } else {
                        img.classList.add('portrait');
                        img.classList.remove('landscape');
                    }
                }
                
                if (captionElement) {
                    captionElement.textContent = img.getAttribute('data-caption');
                }
            } else {
                img.classList.remove('active');
            }
        });
    }
    
    function openModal() {
        const activeImage = document.querySelector('.gallery-image.active');
        if (activeImage && modal && modalImage && modalCaption) {
            modalImage.src = activeImage.src;
            modalImage.alt = activeImage.alt;
            modalCaption.textContent = activeImage.getAttribute('data-caption');
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }
    }
    
    function closeModal() {
        if (modal) {
            modal.classList.remove('active');
            document.body.style.overflow = '';
        }
    }
    
    function updateModal() {
        const activeImage = document.querySelector('.gallery-image.active');
        if (activeImage && modalImage && modalCaption) {
            modalImage.src = activeImage.src;
            modalImage.alt = activeImage.alt;
            modalCaption.textContent = activeImage.getAttribute('data-caption');
        }
    }
    
    updateGallery();
    
    if (prevBtn) {
        prevBtn.addEventListener('click', function() {
            currentImageIndex = (currentImageIndex - 1 + images.length) % images.length;
            updateGallery();
        });
    }
    
    if (nextBtn) {
        nextBtn.addEventListener('click', function() {
            currentImageIndex = (currentImageIndex + 1) % images.length;
            updateGallery();
        });
    }
    
    images.forEach(img => {
        img.addEventListener('click', function() {
            if (this.classList.contains('active')) {
                openModal();
            }
        });
    });
    
    if (modalClose) {
        modalClose.addEventListener('click', closeModal);
    }
    
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                closeModal();
            }
        });
    }
    
    // Modal navigation
    if (modalPrev) {
        modalPrev.addEventListener('click', function() {
            currentImageIndex = (currentImageIndex - 1 + images.length) % images.length;
            updateGallery();
            updateModal();
        });
    }
    
    if (modalNext) {
        modalNext.addEventListener('click', function() {
            currentImageIndex = (currentImageIndex + 1) % images.length;
            updateGallery();
            updateModal();
        });
    }
    
    document.addEventListener('keydown', function(e) {
        if (modal && modal.classList.contains('active')) {
            if (e.key === 'Escape') {
                closeModal();
            } else if (e.key === 'ArrowLeft') {
                currentImageIndex = (currentImageIndex - 1 + images.length) % images.length;
                updateGallery();
                updateModal();
            } else if (e.key === 'ArrowRight') {
                currentImageIndex = (currentImageIndex + 1) % images.length;
                updateGallery();
                updateModal();
            }
        }
    });
});


// FAQ
document.addEventListener('DOMContentLoaded', function() {
    const faqQuestions = document.querySelectorAll('.faq-question');
    
    faqQuestions.forEach(question => {
        question.addEventListener('click', function() {
            const faqItem = this.parentElement;
            
            faqItem.classList.toggle('active');
        });
    });
});


// SQUEAK :3
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


