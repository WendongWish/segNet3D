import math
import torch.nn as nn
import torch.nn.functional as F

__all__ = ['ResNet', 'resnet3d18', 'resnet3d34', 'resnet3d50', 'resnet3d101', 'BasicBlock', 'Bottleneck']

def conv3x3x3(in_planes, out_planes, stride=1):
    return nn.Conv3d(in_planes, out_planes, kernel_size=3, stride=stride, padding=1, bias=False)

class GlobalAvgPool3d(nn.Module):
    def __init__(self):
        super(GlobalAvgPool3d, self).__init__()

    def forward(self, inputs):
        return F.adaptive_avg_pool3d(inputs, 1).view(inputs.size(0), inputs.size(1), -1)

class BasicBlock(nn.Module):
    """
    ResNet Basic Blocks
    """
    expansion = 1
    def __init__(self, inplanes, planes, stride=1, dilation=1, downsample=None, previous_dilation=1, norm_layer=None):
        super(BasicBlock, self).__init__()
        self.conv1 = nn.Conv3d(inplanes, planes, kernel_size=3, stride=stride, padding=dilation, dilation=dilation, bias=False)
        self.bn1 = norm_layer(planes)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv3d(planes, planes, kernel_size=3, stride=1, padding=previous_dilation, dilation=previous_dilation, bias=False)
        self.bn2 = norm_layer(planes)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):

        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)
        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out

class Bottleneck(nn.Module):
    """
    ResNet Bottleneck
    """
    expansion = 4

    def __init__(self, inplanes, planes, stride=1, dilation=1, downsample=None, previous_dilation=1, norm_layer=None):
        super(Bottleneck, self).__init__()

        self.conv1 = nn.Conv3d(inplanes, planes, kernel_size=1, bias=False)
        self.bn1 = norm_layer(planes)
        self.conv2 = nn.Conv3d(planes, planes, kernel_size=3, stride=stride, padding=dilation, dilation=dilation, bias=False)
        self.bn2 = norm_layer(planes)
        self.conv3 = nn.Conv3d(planes, planes * 4, kernel_size=1, bias=False)
        self.bn3 = norm_layer(planes * 4)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.dilation = dilation
        self.stride = stride

    def _sum_each(self, x, y):
        assert(len(x) == len(y))
        z = []
        for i in range(len(x)):
            z.append(x[i] + y[i])
        return z

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out

class ResNet(nn.Module):
    """
    Dilated Pre-trained ResNet Model, which preduces the stride of 8 featuremaps
    Parameters
    ---------
    block : Block
        class for the residual block. Options are BasicBlockV1, BottlenectV1.
    layers : list of int
        Numbers of layers in each block
    dilated : bool, default False
        Applying dilation strategy to pretrained ResNet yielding a stride-8 mode,
        typically used in Semantic Segmentation.
    norm_layer : object
        Normalization layer used in backbone network (default: :class:`mxnet.gluon.nn.BatchNorm`;
        for Synchronized Cross-GPU BachNormalization).
    """
    def __init__(self, block, layers, num_classes=3, dilated=False, norm_layer=nn.BatchNorm3d, multi_grid=False, deep_base=True):
        self.inplanes = 128 if deep_base else 64
        super(ResNet, self).__init__()

        if deep_base:
            self.conv1 = nn.Sequential(
                nn.Conv3d(4, 64, kernel_size=3, stride=2, padding=1, bias=False),
                norm_layer(64),
                nn.ReLU(inplace=True),
                nn.Conv3d(64, 64, kernel_size=3, stride=1, padding=1, bias=False),
                norm_layer(64),
                nn.ReLU(inplace=True),
                nn.Conv3d(64, 128, kernel_size=3, stride=1, padding=1, bias=False),
            )
        else:
            self.conv1 = nn.Conv3d(4, 64, kernel_size=7, stride=2, padding=3, bias=False)
        self.bn1 = norm_layer(self.inplanes)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool3d(kernel_size=3, stride=2, padding=1)
        self.layer1 = self._make_layer(block, 64, layers[0], norm_layer=norm_layer)
        self.layer2 = self._make_layer(block, 128, layers[1], stride=2, norm_layer=norm_layer)

        if dilated:
            self.layer3 = self._make_layer(block, 256, layers[2], stride=1,
                                           dilation=2, norm_layer=norm_layer)
            if multi_grid:
                self.layer4 = self._make_layer(block, 512, layers[3], stride=1,
                                               dilation=4, norm_layer=norm_layer,
                                               multi_grid=True)
            else:
                self.layer4 = self._make_layer(block, 512, layers[3], stride=1,
                                               dilation=4, norm_layer=norm_layer)
        else:
            self.layer3 = self._make_layer(block, 256, layers[2], stride=2,
                                           norm_layer=norm_layer)
            self.layer4 = self._make_layer(block, 512, layers[3], stride=2,
                                           norm_layer=norm_layer)

        self.avgpool = GlobalAvgPool3d()
        self.fc = nn.Linear(512 * block.expansion, num_classes)

        for m in self.modules():
            if isinstance(m, nn.Conv3d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.kernel_size[2] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, norm_layer):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

    def _make_layer(self, block, planes, blocks, stride=1, dilation=1, norm_layer=None, multi_grid=False):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv3d(self.inplanes, planes * block.expansion, kernel_size=1, stride=stride, bias=False),
                norm_layer(planes * block.expansion),
            )
        layers = []
        multi_dilations = [4, 8, 16]
        if multi_grid:
            layers.append(block(self.inplanes, planes, stride, dilation=multi_dilations[0],
                                downsample=downsample, previous_dilation=dilation, norm_layer=norm_layer))
        elif dilation == 1 or dilation == 2:
            layers.append(block(self.inplanes, planes, stride, dilation=1,
                                downsample=downsample, previous_dilation=dilation, norm_layer=norm_layer))
        elif dilation == 4:
            layers.append(block(self.inplanes, planes, stride, dilation=2,
                                downsample=downsample, previous_dilation=dilation, norm_layer=norm_layer))
        else:
            raise RuntimeError("=> unknown dilation size: {}".format(dilation))

        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            if multi_grid:
                layers.append(block(self.inplanes, planes, dilation=multi_dilations[i],
                                    previous_dilation=dilation, norm_layer=norm_layer))
            else:
                layers.append(block(self.inplanes, planes, dilation=dilation, previous_dilation=dilation,
                                    norm_layer=norm_layer))

        return nn.Sequential(*layers)

    def forward(self, x):

        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        x = self.avgpool(x)
        x = x.view(x.size(0), -1)
        x = self.fc(x)

        return x

def resnet3d18(**kwargs):
    model = ResNet(BasicBlock, [2, 2, 2, 2], **kwargs)
    return model

def resnet3d34(**kwargs):
    model = ResNet(BasicBlock, [3, 4, 6, 3], **kwargs)
    return model

def resnet3d50(**kwargs):
    model = ResNet(Bottleneck, [3, 4, 6, 3], **kwargs)
    return model

def resnet3d101(**kwargs):
    model = ResNet(Bottleneck, [3, 4, 23, 3], **kwargs)
    return model

