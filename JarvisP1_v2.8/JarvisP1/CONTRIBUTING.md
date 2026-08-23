# Contributing to J.A.R.V.I.S

Thank you for your interest in contributing to **J.A.R.V.I.S**! We welcome open-source contributions from developers of all skill levels.

---

## 🚀 How to Get Started

1. **Fork the Repository**: Click the "Fork" button at the top right of this repository.
2. **Clone your Fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/JarvisP1.git
   cd JarvisP1
   ```
3. **Create a Feature Branch**:
   ```bash
   git checkout -b feature/amazing-feature
   ```
4. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
5. **Run Jarvis locally**:
   ```bash
   python main.py
   ```

---

## 🛠 Adding New Desktop Apps / Protocol URIs

To register support for new applications:
1. Open `main.py`
2. Add your protocol mapping to `KNOWN_PROTOCOLS`:
   ```python
   KNOWN_PROTOCOLS["myapp"] = "myapp:"
   ```
3. Add a quick launch chip in `index.html`:
   ```html
   <button class="chip-btn" data-cmd="open myapp">🔥 MyApp</button>
   ```

---

## 📝 Pull Request Guidelines

- Ensure your code follows PEP 8 guidelines for Python.
- Keep commits clean and descriptive.
- Open a Pull Request against the `main` branch with a clear description of your changes.

---

## 📜 License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
