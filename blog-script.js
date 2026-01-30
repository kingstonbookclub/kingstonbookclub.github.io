document.addEventListener('DOMContentLoaded', function() {
    const yearToggles = document.querySelectorAll('.blog-year-toggle');
    
    yearToggles.forEach(toggle => {
        toggle.addEventListener('click', function() {
            const content = this.nextElementSibling;
            const icon = this.querySelector('.year-icon');
			
            if (content.classList.contains('collapsed')) {
                content.classList.remove('collapsed');
                this.classList.remove('collapsed');
                icon.textContent = '−';
            } else {
                content.classList.add('collapsed');
                this.classList.add('collapsed');
                icon.textContent = '+';
            }
        });
    });
});

console.log('Blog page loaded');