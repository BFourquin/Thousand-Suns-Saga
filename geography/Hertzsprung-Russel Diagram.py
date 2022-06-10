import sys
import numpy as np
import matplotlib.pyplot as plt

"""
HERTZSPRUNG-RUSSELL DIAGRAM GENERATOR

Python 3.6

This is a Hertzspring-Russell diagram generator, written for use
in Part 10 of the Project variant of the AST2000 course at UiO.

An example on how to generate diagrams is shown at the bottom of
the program.
"""


class HR_Diagram(object):
    def __init__(self, MS_N=800, WD_N=80, RG_N=200, SG_N=60):
        self.star = None
        self.text = None
        self.MS_N = MS_N
        self.WD_N = WD_N
        self.RG_N = RG_N
        self.SG_N = SG_N
        self.s = 4.

    def Main_Sequence(self):
        N = [int(k * self.MS_N) for k in [0.07, 0.14, 0.33, 0.31, 0.15]]
        x1 = np.linspace(0.05, 0.15, N[0]) + np.random.normal(0, 0.01, N[0])
        x2 = np.linspace(0.15, 0.30, N[1]) + np.random.normal(0, 0.02, N[1])
        x3 = np.linspace(0.30, 0.50, N[2]) + np.random.normal(0, 0.04, N[2])
        x4 = np.linspace(0.50, 0.75, N[3]) + np.random.normal(0, 0.04, N[3])
        x5 = np.linspace(0.75, 0.95, N[4]) + np.random.normal(0, 0.01, N[4])
        MS_x = np.concatenate((x1, x2, x3, x4, x5))
        y1 = np.linspace(0.90, 0.65, N[0]) + np.random.normal(0, 0.01, N[0])
        y2 = np.linspace(0.65, 0.50, N[1]) + np.random.normal(0, 0.02, N[1])
        y3 = np.linspace(0.50, 0.40, N[2]) + np.random.normal(0, 0.03, N[2])
        y4 = np.linspace(0.40, 0.30, N[3]) + np.random.normal(0, 0.02, N[3])
        y5 = np.linspace(0.30, 0.10, N[4]) + np.random.normal(0, 0.01, N[4])
        MS_y = np.concatenate((y1, y2, y3, y4, y5))
        return MS_x, MS_y

    def White_Dwarfs(self):
        WD_x = np.linspace(0.20, 0.40, self.WD_N) + np.random.normal(0, 0.10, self.WD_N)
        WD_y = np.linspace(0.15, 0.15, self.WD_N) + np.random.normal(0, 0.05, self.WD_N)
        return WD_x, WD_y

    def Red_Giants(self):
        RG_x = np.linspace(0.60, 0.85, self.RG_N) + np.random.normal(0, 0.05, self.RG_N)
        RG_y = np.linspace(0.50, 0.60, self.RG_N) + np.random.normal(0, 0.03, self.RG_N)
        return RG_x, RG_y

    def Super_Giants(self):
        SG_x = np.linspace(0.60, 0.80, self.SG_N) + np.random.normal(0, 0.15, self.SG_N)
        SG_y = np.linspace(0.80, 0.80, self.SG_N) + np.random.normal(0, 0.10, self.SG_N)
        return SG_x, SG_y

    def star_parameters(self, s, MS_N, WD_N, RG_N, SG_N):
        self.s = float(s)
        self.MS_N = int(MS_N)
        self.WD_N = int(WD_N)
        self.RG_N = int(RG_N)
        self.SG_N = int(SG_N)

    def TL_to_xy(self, T, L):
        if 2.5e3 > T or 4e4 < T or 1e-4 > L or 1e6 < L:
            print("Invalid coordinates, make sure to be within:")
            print("2.5e3  <= T <= 4.0e4")
            print("1.0e-4 <= L <= 1.0e6")
            sys.exit(1)
        a = 1.0 / 6
        step = np.array([4e4, 2e4, 1e4, 7.5e3, 5.5e3, 4.5e3, 2.5e3])
        b, c = step >= T, step - T
        d = np.flatnonzero(b)[-1]
        e = 0 if T in step else a * (step[d] - T) / (step[d] - step[d + 1])
        return a * (sum(b) - 1) + e, (np.log10(L) + 4) / 10.

    def add_star(self, T, L):
        if self.star == None:
            self.star = []
        self.star.append(self.TL_to_xy(T, L))

    def add_text(self, string, T, L):
        if self.text == None:
            self.text = []
        x, y = self.TL_to_xy(T, L)
        self.text.append([x, y, string])

    def generate_diagram(self, title="Hertzsprung-Russell Diagram", filename="HR_diagram.png"):
        MS_x, MS_y = self.Main_Sequence()
        WD_x, WD_y = self.White_Dwarfs()
        RG_x, RG_y = self.Red_Giants()
        SG_x, SG_y = self.Super_Giants()
        X = np.concatenate((MS_x, WD_x, RG_x, SG_x))
        Y = np.concatenate((MS_y, WD_y, RG_y, SG_y))
        idx = np.argsort(X)
        X, Y = X[idx], Y[idx]
        fig = plt.figure("Hertzsprung-Russell Diagram")
        ax = fig.add_subplot(111)
        ax.set_title(title, fontsize=22)
        ax.set_xlabel('Temperature [K]', fontsize=16)
        ax.set_ylabel(r'Luminosity [$L_{\odot}$]', fontsize=16)
        ax.set_xlim(0, 1);
        ax.set_ylim(0, 1)
        ax.scatter(X, Y, s=self.s, c=range(len(Y)), cmap=plt.get_cmap("rainbow"), edgecolor='none')
        ax.set_yticklabels([r'$10^{{{:d}}}$'.format(k) for k in [-4, -2, 0, 2, 4, 6]])
        ax.set_xticks(np.linspace(0, 1, 7))
        ax.set_xticklabels(["40 000", "20 000", "10 000", "7500", "5500", "4500", "2500"])
        if self.star != None:
            for i in range(len(self.star)):
                ax.scatter(self.star[i][0], self.star[i][1], s=64, c='red', edgecolor='none')
        if self.text != None:
            for i in range(len(self.text)):
                ax.text(self.text[i][0], self.text[i][1], self.text[i][2], fontsize=12)
        plt.savefig(filename)
        plt.show()


if __name__ == "__main__":
    # initialize HR Diagram
    Example = HR_Diagram()
    # define star parameters
    Example.star_parameters(s=4., MS_N=800, WD_N=80, RG_N=200, SG_N=60)
    # add a highlighted star to the plot
    Example.add_star(T=7.5e3, L=1)
    Example.add_star(T=4.0e4, L=1.0e4)
    # add text to the plot
    Example.add_text("Main Sequence", T=2e4, L=10 ** 3.1)
    Example.add_text("White Dwarfs", T=3e4, L=10 ** -1.4)
    Example.add_text("Red Giants", T=5e3, L=10 ** 0.4)
    Example.add_text("Super Giants", T=7e3, L=10 ** 4.2)
    # generate final diagram
    Example.generate_diagram()
