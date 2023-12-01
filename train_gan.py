# train_gan.py

import os 
import copy
from typing import Dict, Any, Tuple
import argparse

from tqdm import tqdm

import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader
import torchvision.transforms as transforms
from torchvision import datasets
from torchvision.utils import save_image
import torch.autograd as autograd


from models import Generator, Discriminator 


def parse_args(): 
    parser = argparse.ArgumentParser(description="Train a GAN model on CIFAR-10")
    parser.add_argument("--batch_size", type=int, default=64, help="Batch size for training")
    parser.add_argument("--epochs", type=int, default=2000, help="Number of training epochs")
    parser.add_argument("--lambda_gp", type=int, default=10, help="Lambda for gradient penalty")
    parser.add_argument("--critic_iters", type=int, default=5, help="Number of critic iterations")
    parser.add_argument("--latent_len", type=int, default=128, help="Length of latent vector for generator")
    parser.add_argument("--learning_rate", type=float, default=2e-4, help="Learning rate for optimizers")
    parser.add_argument("--display_step", type=int, default=10, help="Steps for visual inspection")
    parser.add_argument("--save_step", type=int, default=100, help="Steps for saving the model")
    return parser.parse_args()


def calc_gradient_penalty(
        discriminator: nn.Module, 
        real_samples: torch.Tensor, 
        fake_samples: torch.Tensor, 
        device: torch.device, 
        lambda_gp: int = 10,
    ) -> torch.Tensor:

    """
    Calculates the gradient penalty for a batch of real and fake samples to enforce the Lipschitz constraint in WGANs.

    Parameters:
        discriminator (nn.Module): The discriminator model of the GAN.
        real_samples (torch.Tensor): A batch of real samples.
        fake_samples (torch.Tensor): A batch of fake samples generated by the generator.
        device (torch.device): The device on which tensors will be allocated.
        lambda_gp (int, optional): The weight (lambda) for the gradient penalty. Default value is 10.

    Returns:
        torch.Tensor: The calculated gradient penalty.
    """

    batch_size = real_samples.size(0)

    # Random weight term for interpolation between real and fake samples
    alpha = torch.rand(batch_size, 1, 1, 1, device=device)

    # Get random interpolation between real and fake samples
    interpolates = alpha * real_samples + (1 - alpha) * fake_samples
    interpolates = interpolates.to(device).requires_grad_(True)

    d_interpolates = discriminator(interpolates)

    # Create the 'fake' tensor required for autograd.grad
    fake = torch.ones(d_interpolates.size(), requires_grad=False, device=device)

    # Get gradient w.r.t. interpolates
    gradients = autograd.grad(
        outputs=d_interpolates,
        inputs=interpolates,
        grad_outputs=fake,
        create_graph=True,
        retain_graph=True,
        only_inputs=True,
    )[0]

    # Flatten the gradients to compute the norm per sample
    gradients = gradients.view(batch_size, -1)
    gradient_penalty = lambda_gp * ((gradients.norm(2, dim=1) - 1) ** 2).mean()

    return gradient_penalty


def train_gan(
        generator: nn.Module, 
        discriminator: nn.Module, 
        save_name:str, 
        epochs: int,
        checkpoint: Dict[str, Any] = None
    ): 

    optim_G = optim.Adam(generator.parameters(), lr=LEARNING_RATE, betas=(0.5, 0.9))
    optim_D = optim.Adam(discriminator.parameters(), lr=LEARNING_RATE, betas=(0.5, 0.9))

    scheduler_G = CosineAnnealingLR(optim_G, T_max=epochs/CRITIC_ITERS, eta_min=0) 
    scheduler_D = CosineAnnealingLR(optim_D, T_max=epochs, eta_min=0)

    if checkpoint: 
        optim_G.load_state_dict(checkpoint.get('optimizer_G_state_dict'))
        optim_D.load_state_dict(checkpoint.get('optimizer_D_state_dict'))


    grad_direction_fake = torch.tensor(1, dtype=torch.float)
    grad_direction_real = grad_direction_fake * -1

    grad_direction_real = grad_direction_real.to(DEVICE)
    grad_direction_fake = grad_direction_fake.to(DEVICE)

    d_losses = []
    g_losses = []

    for epoch in range(epochs): 

        with tqdm(train_loader, desc=f"Epoch {epoch+1}/{epochs} : D_Loss 0, G_loss 0") as pbar:

            generator.train()
            discriminator.train()

            d_loss_real = 0
            d_loss_fake = 0


            for idx, (real_imgs, _) in enumerate(train_loader): 

                # ---------------------
                # Critic goes first
                # ---------------------

                for param in discriminator.parameters(): 
                    param.requires_grad = True

                optim_D.zero_grad()
                
                real_imgs = autograd.Variable(real_imgs.to(DEVICE))
                
                # sample noise vector for generator input 
                z = autograd.Variable(torch.randn(real_imgs.size(0), LATENT_LEN))
                z = z.to(DEVICE)

                # Pass through Generator 
                fake_imgs = generator(z)

                # Real validity score
                real_validity = discriminator(real_imgs)
                d_loss_real = real_validity.mean()
                d_loss_real.backward(grad_direction_real)
                
                # Fake validity score
                fake_validity = discriminator(fake_imgs) 
                d_loss_fake = fake_validity.mean()
                d_loss_fake.backward(grad_direction_fake)

                # Gradient penalty
                grad_penalty = calc_gradient_penalty(discriminator, real_imgs.data, fake_imgs.data, DEVICE, LAMBDA_GP)
                grad_penalty.backward()

                d_loss = d_loss_fake - d_loss_real + grad_penalty 

                optim_D.step()
                scheduler_D.step()

                del real_imgs

                if (idx + 1) % CRITIC_ITERS == 0 or len(train_loader): 

                    # ---------------------
                    # Update generator
                    # ---------------------

                    for param in discriminator.parameters(): 
                        param.requires_grad = False

                    # Generate fake images using sampled noise from before
                    fake_imgs = generator(z)
                    
                    optim_G.zero_grad()

                    # Calculate and pass back generator loss
                    validity_score = discriminator(fake_imgs)
                    g_loss = validity_score.mean()
                    g_loss.backward(grad_direction_real)

                    optim_G.step()
                    scheduler_G.step()

                pbar.update(1)
                pbar.set_description(f"Epoch {epoch+1}/{epochs} : D_Loss {round(d_loss.item(), 6)}, G_loss {round(g_loss.item(), 6)}")
        
        g_losses.append(g_loss.item())
        d_losses.append(d_loss.item())

        if (epoch + 1) % DISPLAY_STEP == 0: 
            # Save debug image 
            debug_output = generator(DEBUG_VECTOR)
            save_image(debug_output.data, os.path.join(DEBUG_PATH, f'debug_{epoch+1}.png'), normalize=True)
            

        if (epoch + 1) % SAVE_STEP == 0: 
            spath = os.path.join(SAVES_PATH, save_name+'.pth')

            print(f"Saving Checkpoint at epoch {epoch+1} to {spath}")
            
            generator_copy = copy.deepcopy(generator).cpu()
            discriminator_copy = copy.deepcopy(discriminator).cpu()
          
            torch.save({
                'epoch': epoch + 1,
                'generator_state_dict': generator_copy.state_dict(),
                'discriminator_state_dict': discriminator_copy.state_dict(),
                'optimizer_G_state_dict': optim_G.state_dict(),
                'optimizer_D_state_dict': optim_D.state_dict(),
            }, spath)

            del generator_copy
            
    return [g_losses, d_losses]


    

if __name__ == '__main__':
    args = parse_args()

    # Hyperparams
    BATCH_SIZE = args.batch_size
    EPOCHS = args.epochs
    LAMBDA_GP = args.lambda_gp
    CRITIC_ITERS = args.critic_iters
    LATENT_LEN = args.latent_len
    LEARNING_RATE = args.learning_rate
    DISPLAY_STEP = args.display_step
    SAVE_STEP = args.save_step
    DEVICE = torch.device('cuda')
    SAVES_PATH = os.path.join('models', 'checkpoints', 'gans')
    DEBUG_PATH = os.path.join('debug_imgs')
    DEBUG_VECTOR = torch.randn(BATCH_SIZE, LATENT_LEN).to(DEVICE) # constant input for visual debugging of the generator


    # Data transformations
    mean, std = [-0.0541, -0.0127,  0.0265], [0.9868, 1.0000, 1.0029]

    data_transforms = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean, std)
    ])

    # DataLoader setup
    trainset = datasets.CIFAR10(root='./data', train=True, download=True, transform=data_transforms)
    train_loader = DataLoader(trainset, batch_size=BATCH_SIZE, num_workers=4, shuffle=True)

    generator = Generator(LATENT_LEN, 128)
    discriminator = Discriminator(256)

    #checkpoint = torch.load(os.path.join('models', 'checkpoints', 'gans', 'defensegan_128_v2.pth'))

    #generator.load_state_dict(checkpoint.get('generator_state_dict'))
    #discriminator.load_state_dict(checkpoint.get('discriminator_state_dict'))

    generator = generator.to(DEVICE)
    discriminator = discriminator.to(DEVICE)

    train_data = train_gan(generator, discriminator, 'defensegan_256',   EPOCHS)# EPOCHS - checkpoint.get('epoch'), checkpoint=checkpoint)

