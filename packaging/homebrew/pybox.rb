# Homebrew formula template for a future tap (github.com/ctxnn/homebrew-pybox).
# Points at the 0.3.0 release on PyPI. Publish it in a tap repo, then: brew install ctxnn/pybox/pybox
class Pybox < Formula
  include Language::Python::Virtualenv

  desc "Run Python you don't trust in a fresh, sealed box on your Mac, with a receipt"
  homepage "https://ctxnn.github.io/pybox"
  url "https://files.pythonhosted.org/packages/source/p/pybox-sandbox/pybox_sandbox-0.3.0.tar.gz"
  sha256 "84ec2f8b8d0ab70458be2d6495c3ddc6891638f52bc5217a7278b3a7e7433648"
  license "Apache-2.0"

  depends_on arch: :arm64
  depends_on "colima"
  depends_on "docker"
  depends_on :macos
  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      Create the sealed runtime once (it shows its plan first):
        pybox setup
        pybox setup --yes
      Then:
        pybox vm start
        echo 'print(6*7)' | pybox exec -
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/pybox --version")
  end
end
