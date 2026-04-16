mod jujuignore;
mod metadata;
mod pack;
mod parts;

use clap::Parser;
use std::path::PathBuf;
use std::time::Instant;

/// Fast local charm packing for development workflows.
#[derive(Parser)]
#[command(name = "quickpack")]
#[command(about = "Fast local charm packing for development workflows.")]
struct Cli {
    /// Path to the charm project directory (default: current directory).
    #[arg(default_value = ".")]
    charm_dir: PathBuf,

    /// Directory to write the .charm file to (default: charm directory).
    #[arg(short, long)]
    output_dir: Option<PathBuf>,

    /// Suppress progress output.
    #[arg(short, long)]
    quiet: bool,
}

fn main() {
    let cli = Cli::parse();

    let charm_dir = cli.charm_dir.canonicalize().unwrap_or_else(|_| {
        eprintln!("Error: {} is not a directory", cli.charm_dir.display());
        std::process::exit(1);
    });

    if !charm_dir.is_dir() {
        eprintln!("Error: {} is not a directory", charm_dir.display());
        std::process::exit(1);
    }

    let charmcraft_yaml = charm_dir.join("charmcraft.yaml");
    if !charmcraft_yaml.exists() {
        eprintln!(
            "Error: charmcraft.yaml not found in {}",
            charm_dir.display()
        );
        std::process::exit(1);
    }

    if !cli.quiet {
        println!("Packing charm in {} ...", charm_dir.display());
    }

    let start = Instant::now();

    match pack::quick_pack(&charm_dir, cli.output_dir.as_deref()) {
        Ok(charm_path) => {
            let elapsed = start.elapsed();
            if !cli.quiet {
                println!(
                    "Created {} in {:.1}s",
                    charm_path
                        .file_name()
                        .map(|f| f.to_string_lossy().to_string())
                        .unwrap_or_default(),
                    elapsed.as_secs_f64()
                );
            }
        }
        Err(e) => {
            eprintln!("Error: {e}");
            std::process::exit(1);
        }
    }
}
